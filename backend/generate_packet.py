"""Claim packet generation module.

Assembles the final `ClaimPacket`:
  - Drafts an incident summary and FNOL letter via Gemini 2.5 Flash.
  - Renders `templates/packet.html` with Jinja2 (cover page, summary,
    FNOL, itemized inventory with embedded thumbnails, policy
    references, and an evidence-trail footer).
  - Renders the HTML to PDF using headless Chromium via Playwright.

Public entry point: `generate_packet(...)`.

The PDF is the central deliverable of the product; this module is the
last stage of the pipeline before review.
"""

from __future__ import annotations

import base64
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

import config
import gemini_retry
from schemas import ClaimPacket, InventoryItem, NarrationChunk, PolicySection

GEMINI_MODEL: str = "gemini-2.5-flash"
TEMPLATE_DIR: Path = Path(__file__).parent / "templates"
TEMPLATE_NAME: str = "packet.html"
POLICY_TEXT_EXCERPT_CHARS: int = 500

# Whisper occasionally mangles brand names. Apply targeted substitutions
# before the narration is shown to Gemini or to the human reader.
TYPO_FIXES: dict[str, str] = {
    "Highsense": "Hisense",
    "highsense": "Hisense",
}


def _apply_typo_fixes(text: str) -> str:
    for bad, good in TYPO_FIXES.items():
        text = text.replace(bad, good)
    return text


# ---------------------------------------------------------------------------
# Gemini text-only helpers (separate client cache from detect_inventory)
# ---------------------------------------------------------------------------

_gemini_client: Any | None = None


def _get_gemini_client() -> Any:
    global _gemini_client
    if _gemini_client is None:
        if not config.GOOGLE_API_KEY:
            raise RuntimeError(
                "GOOGLE_API_KEY is not set; cannot call Gemini. "
                "Add it to backend/.env."
            )
        from google import genai
        _gemini_client = genai.Client(api_key=config.GOOGLE_API_KEY)
    return _gemini_client


def _gemini_text(prompt: str) -> str:
    """Single-prompt text generation with shared 429/5xx retry."""
    client = _get_gemini_client()
    response = gemini_retry.call_with_retry(
        client,
        log_prefix="[generate_packet]",
        model=GEMINI_MODEL,
        contents=[prompt],
    )
    return (getattr(response, "text", None) or "").strip()


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_summary_prompt(narration: list[NarrationChunk], intake: dict) -> str:
    joined = " ".join(c.text for c in narration).strip() or "(no narration)"
    joined = _apply_typo_fixes(joined)
    return (
        "You are writing the incident summary section of an insurance "
        "claim packet. Based on the following narration from the "
        "claimant's walkthrough video and incident details, write 2-3 "
        "sentences describing what happened, in a factual, claim-"
        "appropriate tone. Do not editorialize. Do not speculate about "
        "cause. Do not use first person.\n\n"
        f"Incident date: {intake.get('incident_date', 'unspecified')}\n"
        f"Cause: {intake.get('cause', 'unspecified')}\n"
        f"Location: {intake.get('location', 'unspecified')}\n"
        f"Narration: {joined}"
    )


def _build_fnol_prompt(items: list[InventoryItem], intake: dict) -> str:
    categories = sorted({it.category for it in items}) or ["personal property"]
    claimant = intake.get("claimant_name", "Policyholder")
    return (
        "Write ONLY the body of a First Notice of Loss letter. Output "
        "must START with 'Dear Claims Department,' and END with a "
        "complimentary close followed by the claimant's name on the "
        "next line.\n\n"
        "DO NOT include:\n"
        "- Any sender address, city, postal code, phone, or email\n"
        "- Any recipient address beyond what's already in the template\n"
        "- Any date line\n"
        "- Any placeholder text in square brackets like [Your Name]\n"
        "- Any subject line (the template provides this)\n\n"
        "The letter should be 3-4 paragraphs. Factual tone. Reference "
        "the incident date and cause. Summarize damage scope. Request "
        "adjuster assignment. Close with 'Sincerely,' on one line and "
        f"'{claimant}' on the next.\n\n"
        f"Claimant name: {claimant}\n"
        f"Incident date: {intake.get('incident_date', 'unspecified')}\n"
        f"Cause: {intake.get('cause', 'unspecified')}\n"
        f"Number of damaged items: {len(items)}\n"
        f"Item categories affected: {', '.join(categories)}\n\n"
        "OUTPUT: the letter body only, starting with 'Dear Claims Department,'"
    )


# ---------------------------------------------------------------------------
# Image / template helpers
# ---------------------------------------------------------------------------

def _frame_path(claim_id: str, frame_id: str) -> Path:
    return Path(config.OUTPUT_DIR) / claim_id / "frames" / f"{frame_id}.jpg"


def _image_to_data_uri(path: Path) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _build_thumbnails(claim_id: str, items: list[InventoryItem]) -> dict[str, str]:
    """Pick a representative thumbnail per item.

    Uses the *middle* source frame rather than the first because the
    first frame is often a transition (item entering the shot, motion
    blur, partial occlusion). The middle frame is empirically the most
    centered/clean view of the item.
    """
    thumbs: dict[str, str] = {}
    for it in items:
        if not it.source_frame_ids:
            continue
        mid_idx = len(it.source_frame_ids) // 2
        uri = _image_to_data_uri(_frame_path(claim_id, it.source_frame_ids[mid_idx]))
        if uri:
            thumbs[it.item_id] = uri
    return thumbs


def _collect_cited_sections(
    items: list[InventoryItem], sections: list[PolicySection]
) -> list[dict[str, Any]]:
    by_id: dict[str, PolicySection] = {s.section_id: s for s in sections}
    seen: set[str] = set()
    ordered_ids: list[str] = []
    for it in items:
        for sid in it.policy_citations:
            if sid not in seen and sid in by_id:
                seen.add(sid)
                ordered_ids.append(sid)
    out: list[dict[str, Any]] = []
    for sid in ordered_ids:
        sec = by_id[sid]
        text = sec.text or ""
        excerpt = text[:POLICY_TEXT_EXCERPT_CHARS]
        out.append({
            "section_id": sec.section_id,
            "title": sec.title,
            "text_excerpt": excerpt,
            "truncated": len(text) > POLICY_TEXT_EXCERPT_CHARS,
        })
    return out


def _render_html(
    packet: ClaimPacket,
    items: list[InventoryItem],
    sections: list[PolicySection],
    intake: dict,
    thumbs: dict[str, str],
    video_filename: str,
    policy_filename: str,
    frame_count: Optional[int],
) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template(TEMPLATE_NAME)
    return template.render(
        packet=packet,
        items=items,
        intake=intake,
        thumbs=thumbs,
        cited_sections=_collect_cited_sections(items, sections),
        generated_long=datetime.now().strftime("%B %d, %Y"),
        video_filename=video_filename,
        policy_filename=policy_filename,
        frame_count=frame_count,
    )


# ---------------------------------------------------------------------------
# PDF rendering (headless Chromium via Playwright)
#
# Uses sync_playwright on purpose. generate_packet() is invoked from
# synchronous call sites — `regenerate_packet` (sync FastAPI endpoint)
# and the BackgroundTasks threadpool worker that runs `run_pipeline`.
# Calling `asyncio.run()` from a non-main thread on Windows can
# deadlock indefinitely waiting on the Proactor IOCP loop, which we
# observed as the "rendering PDF" step hanging forever with no
# Chromium child process. sync_playwright runs the driver in its own
# subprocess and avoids the issue entirely.
# ---------------------------------------------------------------------------

PDF_MARGIN = {
    "top": "0.5in",
    "right": "0.5in",
    "bottom": "0.5in",
    "left": "0.5in",
}


def _render_pdf(html: str, output_pdf_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(
                path=str(output_pdf_path),
                format="Letter",
                margin=PDF_MARGIN,
                print_background=True,
            )
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_packet(
    claim_id: str,
    items: list[InventoryItem],
    policy_sections: list[PolicySection],
    intake: dict,
    video_source_path: str,
    policy_source_path: str,
    output_pdf_path: Optional[str] = None,
    narration: Optional[list[NarrationChunk]] = None,
    frame_count: Optional[int] = None,
) -> ClaimPacket:
    """Render the final claim packet PDF and return a populated `ClaimPacket`.

    Args:
        claim_id: identifier used for output paths and the cover page.
        items: detected & cited inventory items for the claim.
        policy_sections: full set of parsed policy sections (used to
            resolve citation IDs back to titles + text).
        intake: dict with keys `incident_date`, `cause`, `location`,
            `claimant_name`.
        video_source_path: path to the source walkthrough video.
        policy_source_path: path to the source policy PDF.
        output_pdf_path: where to write the rendered PDF. Defaults to
            `./outputs/{claim_id}/packet.pdf`.
        narration: optional narration chunks used for the incident
            summary prompt. If omitted, the summary falls back to
            intake-only context.
        frame_count: optional count of analyzed keyframes for the
            evidence-trail footer. If None, the line is omitted.
    """
    out_path = Path(output_pdf_path) if output_pdf_path else (
        Path(config.OUTPUT_DIR) / claim_id / "packet.pdf"
    )
    narration = narration or []

    print("[generate_packet] drafting incident summary via Gemini")
    incident_summary = _gemini_text(_build_summary_prompt(narration, intake))

    print("[generate_packet] drafting FNOL letter via Gemini")
    fnol_letter = _gemini_text(_build_fnol_prompt(items, intake))

    total_estimated = sum(it.estimated_value or 0.0 for it in items)
    verified = sum(
        (it.estimated_value or 0.0) for it in items if it.proof_attached
    )

    cited_ids = sorted({sid for it in items for sid in it.policy_citations})
    cited_sections_full = [s for s in policy_sections if s.section_id in cited_ids]

    packet = ClaimPacket(
        claim_id=claim_id,
        incident_summary=incident_summary,
        incident_date=intake.get("incident_date", ""),
        items=items,
        total_estimated_value=total_estimated,
        verified_value=verified,
        policy_sections_cited=cited_sections_full,
        fnol_letter=fnol_letter,
        video_source_path=video_source_path,
        policy_source_path=policy_source_path,
        pdf_path=None,
    )

    print("[generate_packet] building thumbnails")
    thumbs = _build_thumbnails(claim_id, items)

    print("[generate_packet] rendering HTML")
    html = _render_html(
        packet=packet,
        items=items,
        sections=policy_sections,
        intake=intake,
        thumbs=thumbs,
        video_filename=Path(video_source_path).name,
        policy_filename=Path(policy_source_path).name,
        frame_count=frame_count,
    )

    print(f"[generate_packet] rendering PDF -> {out_path}")
    _render_pdf(html, out_path)

    packet.pdf_path = str(out_path)
    return packet


# ---------------------------------------------------------------------------
# __main__ — local end-to-end run on the test claim
# ---------------------------------------------------------------------------

def _load_items_from_json(path: Path) -> list[InventoryItem]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [InventoryItem(**d) for d in raw]


def _load_narration_from_cache(claim_id: str) -> list[NarrationChunk]:
    cache_path = Path(config.OUTPUT_DIR) / claim_id / "ingest_cache.json"
    if not cache_path.is_file():
        return []
    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [NarrationChunk(**c) for c in data.get("narration", [])]


def _frame_count_from_cache(claim_id: str) -> Optional[int]:
    cache_path = Path(config.OUTPUT_DIR) / claim_id / "ingest_cache.json"
    if not cache_path.is_file():
        return None
    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    frames = data.get("frames")
    return len(frames) if isinstance(frames, list) else None


if __name__ == "__main__":
    claim_id = sys.argv[1] if len(sys.argv) > 1 else "test"

    inv_path = Path(config.OUTPUT_DIR) / claim_id / "inventory_with_citations.json"
    if not inv_path.is_file():
        # fall back to the un-cited inventory if the citations step wasn't run
        inv_path = Path(config.OUTPUT_DIR) / claim_id / "inventory.json"
    if not inv_path.is_file():
        print(f"[main] no inventory file found for claim={claim_id!r}; "
              "run detect_inventory (and ideally search_policy) first")
        sys.exit(1)
    items = _load_items_from_json(inv_path)
    print(f"[main] loaded {len(items)} items from {inv_path}")

    print("[main] re-parsing demo_policy.pdf for section text")
    from ingest_policy import ingest_policy
    policy_pdf = "demo_policy.pdf"
    sections = ingest_policy(policy_pdf)
    print(f"[main] parsed {len(sections)} policy sections")

    narration = _load_narration_from_cache(claim_id)
    frame_count = _frame_count_from_cache(claim_id)
    print(f"[main] loaded {len(narration)} narration chunks "
          f"and {frame_count} keyframes from cache")

    intake = {
        "incident_date": "April 18, 2026",
        "cause": "Water damage from pipe burst",
        "location": "Living room and bedroom",
        "claimant_name": "Hedi Bouassida",
    }

    packet = generate_packet(
        claim_id=claim_id,
        items=items,
        policy_sections=sections,
        intake=intake,
        video_source_path="real-video.mp4",
        policy_source_path=policy_pdf,
        narration=narration,
        frame_count=frame_count,
    )

    print(f"\n[main] PDF written to: {packet.pdf_path}")
    print(f"[main] incident summary preview: {packet.incident_summary[:160]!r}")
    print(f"[main] FNOL preview:             {packet.fnol_letter[:160]!r}")

    # also persist the assembled packet metadata for inspection
    meta_path = Path(config.OUTPUT_DIR) / claim_id / "packet_meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        meta = asdict(packet)
        # the items/policy_sections lists already serialize fine via asdict
        json.dump(meta, f, indent=2)
    print(f"[main] packet metadata written to: {meta_path}")
