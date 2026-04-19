"""Inventory detection via Gemini 2.5 Flash.

Slides a 6-second window (with 2s overlap) over the video timeline,
asks Gemini for a list of damaged/relevant inventory items per
window using the in-window keyframes and overlapping narration, then
deduplicates detections across windows using a name-similarity +
time-proximity rule. Produces fully-populated `InventoryItem`s
(minus value/policy fields, which are filled by later stages).
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import asdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from PIL import Image

import config
import gemini_retry
import vector_store
from schemas import InventoryItem, KeyFrame, NarrationChunk

WINDOW_SEC: float = 10.0
WINDOW_STRIDE_SEC: float = 8.0  # 10s window, 2s overlap → stride 8s
MAX_FRAMES_PER_WINDOW: int = 4
NAME_SIMILARITY_THRESHOLD: float = 0.7
TIME_PROXIMITY_SEC: float = 8.0
GEMINI_MODEL: str = "gemini-2.5-flash"

# Tier 1 (paid) on gemini-2.5-flash allows ~1000 RPM. Keep a tiny 0.5s
# spacing as a courtesy gap; gemini_retry.call_with_retry handles 429 +
# 5xx transients reactively.
MIN_SECONDS_BETWEEN_CALLS: float = 0.5
_last_call_time: float = 0.0

VALID_CATEGORIES: set[str] = {
    "electronics", "furniture", "textile", "appliance",
    "decor", "clothing", "other",
}

# Tokens that are too generic to be considered a brand signal.
STOPWORDS: set[str] = {
    "the", "a", "an", "and", "or", "with", "for",
    "my", "this", "that", "these", "those",
}
GENERIC_CATEGORY_WORDS: set[str] = {
    "tv", "computer", "laptop", "phone", "headphones", "speaker",
    "lamp", "rug", "chair", "table", "camera", "watch", "remote",
    "keyboard", "mouse", "monitor", "bed", "book", "books",
}
# Words that indicate an item is an accessory of a primary device. Used
# to block brand-token merges across the primary/accessory boundary
# (e.g. "Hisense TV" should NOT merge with "Hisense ROKU TV Remote"
# even though they share the "hisense" brand token).
ACCESSORY_WORDS: set[str] = {
    "remote", "controller", "charger", "cable", "case", "cover",
    "stand", "mount", "adapter", "keyboard", "mouse",
}

# Whisper occasionally mangles brand names; patch them before they reach
# Gemini so per-window detection sees the correct brand spelling.
TYPO_FIXES: dict[str, str] = {
    "Highsense": "Hisense",
    "highsense": "Hisense",
}


def _apply_typo_fixes(text: str) -> str:
    for bad, good in TYPO_FIXES.items():
        text = text.replace(bad, good)
    return text

_PROMPT_TEMPLATE = """You are analyzing a segment of an insurance claim video walkthrough.
The user is documenting damage to their personal property.

SEGMENT CONTEXT:
- Time window: {start_sec:.1f}s to {end_sec:.1f}s of the video
- Incident type: {incident_type}
- User's narration in this segment: "{narration_text}"
- You are shown {n_frames} keyframe(s) from this segment.

YOUR TASK:
Identify every DISTINCT physical inventory item that is either:
(a) visible in the frames AND mentioned in the narration, OR
(b) explicitly named in the narration (even if not clearly visible).

For each item, return a JSON object with these fields:
- name: specific item name, include brand/model if stated or clearly visible
        (e.g. "MacBook Pro 14-inch" not just "laptop")
- category: one of ["electronics", "furniture", "textile", "appliance",
                    "decor", "clothing", "other"]
- description: 1-sentence description of visible attributes
                (material, color, size, condition-relevant details)
- damage_observed: what the user said is wrong with it, or what you
                    can see is wrong. Empty string if none mentioned.
- confidence: 0.0-1.0. High (>0.8) if narration clearly names it AND
              it's visible. Medium (0.5-0.8) if only one signal. Low
              (<0.5) if you're guessing.
- brand_recognized: true ONLY if a specific brand/model is named in
                    narration OR a clear brand logo is visible.
                    Otherwise false.

STRICT RULES:
- Return ONLY items the user is documenting as damaged, lost, or
  relevant to the claim. Skip background items they don't discuss.
- If narration says "this MacBook" and a laptop is visible, that is
  ONE item with brand_recognized=true.
- Do not invent brands. Do not assume models. Do not guess values.
- If narration is empty or describes no items, return an empty array.
- If an item is mentioned multiple times in the narration, still
  return it only once per window.

Return STRICTLY this JSON structure, no prose before or after:
{{
  "items": [
    {{
      "name": "...",
      "category": "...",
      "description": "...",
      "damage_observed": "...",
      "confidence": 0.0,
      "brand_recognized": false
    }}
  ]
}}"""


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


def _validate_category(c: str) -> str:
    c = (c or "").strip().lower()
    return c if c in VALID_CATEGORIES else "other"


def _clamp01(x: Any) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def _frames_in_window(
    frames: list[KeyFrame], start: float, end: float
) -> list[KeyFrame]:
    in_win = [f for f in frames if start <= f.timestamp_sec <= end]
    if len(in_win) > MAX_FRAMES_PER_WINDOW:
        step = len(in_win) / MAX_FRAMES_PER_WINDOW
        in_win = [in_win[int(i * step)] for i in range(MAX_FRAMES_PER_WINDOW)]
    return in_win


def _timeline_end(
    frames: list[KeyFrame], narration: list[NarrationChunk]
) -> float:
    candidates: list[float] = []
    if frames:
        candidates.append(max(f.timestamp_sec for f in frames))
    if narration:
        candidates.append(max(c.end_sec for c in narration))
    return max(candidates) if candidates else 0.0


def _windows(end_time: float) -> list[tuple[float, float]]:
    if end_time <= 0:
        return []
    out: list[tuple[float, float]] = []
    t = 0.0
    while t < end_time:
        out.append((t, t + WINDOW_SEC))
        t += WINDOW_STRIDE_SEC
    return out


def _generate_with_retry(client: Any, **kwargs: Any) -> Any:
    """Throttle gently, then dispatch to the shared retry helper.

    Throttle is local because it only matters for the per-window loop
    here (generate_packet only fires twice per packet). Retry policy
    for 429 / 500 / 503 / 504 lives in `gemini_retry`.
    """
    global _last_call_time

    now = time.monotonic()
    elapsed = now - _last_call_time if _last_call_time > 0 else float("inf")
    if elapsed < MIN_SECONDS_BETWEEN_CALLS:
        time.sleep(MIN_SECONDS_BETWEEN_CALLS - elapsed)
        elapsed = time.monotonic() - _last_call_time

    elapsed_str = f"{elapsed:.1f}" if elapsed != float("inf") else "first"
    print(f"[detect_inventory] Gemini call (elapsed {elapsed_str}s since last)")

    try:
        return gemini_retry.call_with_retry(
            client, log_prefix="[detect_inventory]", **kwargs
        )
    finally:
        _last_call_time = time.monotonic()


def _call_gemini(
    prompt: str, pil_images: list[Image.Image]
) -> dict[str, Any] | None:
    """Send a multimodal request and return parsed JSON, or None on bad output."""
    client = _get_gemini_client()
    try:
        response = _generate_with_retry(
            client,
            model=GEMINI_MODEL,
            contents=[prompt, *pil_images],
            config={"response_mime_type": "application/json"},
        )
    except Exception as e:
        print(f"[detect_inventory] Gemini SDK error (after retries): {e}")
        raise

    raw = getattr(response, "text", None) or ""
    try:
        return json.loads(raw)
    except (ValueError, TypeError) as e:
        print(f"[detect_inventory] malformed JSON from Gemini ({e}); raw[:200]={raw[:200]!r}")
        return None


def _detect_window(
    window_frames: list[KeyFrame],
    narration_text: str,
    start: float,
    end: float,
    incident_context: Optional[str],
) -> list[dict[str, Any]]:
    prompt = _PROMPT_TEMPLATE.format(
        start_sec=start,
        end_sec=end,
        incident_type=incident_context or "unspecified property damage",
        narration_text=narration_text.replace('"', "'"),
        n_frames=len(window_frames),
    )

    pil_images: list[Image.Image] = []
    for f in window_frames:
        try:
            img = Image.open(f.image_path)
            img.load()
            pil_images.append(img)
        except Exception as e:
            print(f"[detect_inventory] failed to open {f.image_path}: {e}")

    if not pil_images:
        return []

    parsed = _call_gemini(prompt, pil_images)
    if parsed is None:
        return []

    raw_items = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(raw_items, list):
        print(f"[detect_inventory] window {start:.1f}-{end:.1f}s: 'items' missing or not a list")
        return []

    cleaned: list[dict[str, Any]] = []
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name", "")).strip()
        if not name:
            continue
        cleaned.append({
            "name": name,
            "category": _validate_category(str(it.get("category", "other"))),
            "description": str(it.get("description", "")).strip(),
            "damage_observed": str(it.get("damage_observed", "")).strip(),
            "confidence": _clamp01(it.get("confidence", 0.0)),
            "brand_recognized": bool(it.get("brand_recognized", False)),
        })
    return cleaned


def _brand_tokens(name: str) -> set[str]:
    """Extract candidate brand tokens from an item name.

    A brand token is a 3+ char word in the ORIGINAL (case-preserved)
    name that starts with an uppercase letter and isn't a stopword
    or generic category word. e.g. "Hisense" or "Lenovo" qualify;
    "TV", "the", "Laptop" do not.
    """
    tokens: set[str] = set()
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9\-]*", name):
        if len(raw) < 3 or not raw[0].isupper():
            continue
        low = raw.lower()
        if low in STOPWORDS or low in GENERIC_CATEGORY_WORDS:
            continue
        tokens.add(low)
    return tokens


def _share_brand_token(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return bool(_brand_tokens(a["name"]) & _brand_tokens(b["name"]))


def _category_compatible(c1: str, c2: str) -> bool:
    """Same category, or one side is 'other' (softens the gate so a
    brand-tagged item categorized vaguely as 'other' can still merge
    with the same brand item categorized specifically)."""
    return c1 == c2 or c1 == "other" or c2 == "other"


def _has_accessory_word(name: str) -> bool:
    tokens = {t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9\-]*", name)}
    return bool(tokens & ACCESSORY_WORDS)


def _accessory_mismatch(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True iff exactly one of the two names contains an accessory word.

    Used to block brand-token merges across the primary/accessory
    boundary, so e.g. "Hisense TV" and "Hisense ROKU TV Remote" stay
    as separate items despite sharing the "hisense" brand token.
    """
    return _has_accessory_word(a["name"]) != _has_accessory_word(b["name"])


def _same_item(a: dict[str, Any], b: dict[str, Any]) -> bool:
    # Brand-token rule: shared brand token (e.g. "Hisense", "Lenovo",
    # "Pixel") + compatible category → same physical object regardless
    # of how far apart in the video they were re-described.
    # Blocked when one side is an accessory (remote, charger, etc.) and
    # the other is the primary device.
    if (
        _share_brand_token(a, b)
        and _category_compatible(a["category"], b["category"])
        and not _accessory_mismatch(a, b)
    ):
        return True

    if a["category"] != b["category"]:
        return False
    sim = SequenceMatcher(None, a["name"].lower(), b["name"].lower()).ratio()
    if sim < NAME_SIMILARITY_THRESHOLD:
        return False
    overlap = (
        a["first_seen_sec"] <= b["last_seen_sec"]
        and a["last_seen_sec"] >= b["first_seen_sec"]
    )
    if overlap:
        return True
    gap = max(a["first_seen_sec"], b["first_seen_sec"]) - min(
        a["last_seen_sec"], b["last_seen_sec"]
    )
    return gap <= TIME_PROXIMITY_SEC


def _cluster(detections: list[dict[str, Any]]) -> list[list[int]]:
    """Union-find clustering over detection indices."""
    n = len(detections)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if _same_item(detections[i], detections[j]):
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _merge_cluster(items: list[dict[str, Any]]) -> dict[str, Any]:
    best = max(items, key=lambda d: d["confidence"])
    descriptions = [it["description"] for it in items if it["description"]]
    damages = [it["damage_observed"] for it in items if it["damage_observed"]]
    frame_ids = sorted({fid for it in items for fid in it["source_frame_ids"]})
    chunk_ids = sorted({cid for it in items for cid in it["source_narration_ids"]})
    return {
        "name": best["name"],
        "category": items[0]["category"],
        "description": max(descriptions, key=len) if descriptions else "",
        "damage_observed": max(damages, key=len) if damages else "",
        "confidence": max(it["confidence"] for it in items),
        "brand_recognized": any(it["brand_recognized"] for it in items),
        "source_frame_ids": frame_ids,
        "source_narration_ids": chunk_ids,
        "first_seen_sec": min(it["first_seen_sec"] for it in items),
        "last_seen_sec": max(it["last_seen_sec"] for it in items),
    }


def detect_inventory(
    frames: list[KeyFrame],
    narration: list[NarrationChunk],
    claim_id: str,
    incident_context: Optional[str] = None,
) -> list[InventoryItem]:
    """Run the full detection + dedup pipeline for one claim."""
    end_time = _timeline_end(frames, narration)
    if end_time <= 0:
        print("[detect_inventory] empty timeline; nothing to detect")
        return []

    raw_detections: list[dict[str, Any]] = []

    for start, end in _windows(end_time):
        window_frames = _frames_in_window(frames, start, end)
        chunks_in_win = vector_store.search_narration_by_time(claim_id, start, end)
        narration_text = _apply_typo_fixes(
            " ".join(c["text"] for c in chunks_in_win).strip()
        )

        if not window_frames or not narration_text:
            continue

        detections = _detect_window(
            window_frames, narration_text, start, end, incident_context
        )
        print(
            f"[detect_inventory] window {start:5.1f}-{end:5.1f}s | "
            f"frames={len(window_frames)} chunks={len(chunks_in_win)} | "
            f"items_detected={len(detections)}"
        )

        for d in detections:
            d["source_frame_ids"] = [f.frame_id for f in window_frames]
            d["source_narration_ids"] = [c["chunk_id"] for c in chunks_in_win]
            d["first_seen_sec"] = start
            d["last_seen_sec"] = end
            raw_detections.append(d)

    print(f"[detect_inventory] raw detections across all windows: {len(raw_detections)}")

    clusters = _cluster(raw_detections)
    merged = [_merge_cluster([raw_detections[i] for i in cluster]) for cluster in clusters]
    print(f"[detect_inventory] merged into {len(merged)} unique items")

    inventory: list[InventoryItem] = []
    for i, m in enumerate(merged):
        item = InventoryItem(
            item_id=f"item_{i:02d}",
            name=m["name"],
            category=m["category"],
            description=m["description"],
            damage_observed=m["damage_observed"],
            confidence=m["confidence"],
            source_frame_ids=m["source_frame_ids"],
            source_narration_ids=m["source_narration_ids"],
            first_seen_sec=m["first_seen_sec"],
            last_seen_sec=m["last_seen_sec"],
            brand_recognized=m["brand_recognized"],
            estimated_value=None,
            value_source="unknown",
            proof_attached=False,
            policy_citations=[],
        )
        inventory.append(item)
        print(
            f"  - {item.item_id} {item.name!r} "
            f"conf={item.confidence:.2f} brand={item.brand_recognized}"
        )

    return inventory


# ---------------------------------------------------------------------------
# __main__: glue + caching for local end-to-end runs
# ---------------------------------------------------------------------------

def _cache_path(claim_id: str) -> Path:
    return Path(config.OUTPUT_DIR) / claim_id / "ingest_cache.json"


def _load_cache(
    claim_id: str,
) -> tuple[list[KeyFrame], list[NarrationChunk]] | None:
    p = _cache_path(claim_id)
    if not p.is_file():
        return None
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    frames = [KeyFrame(**f) for f in data["frames"]]
    chunks = [NarrationChunk(**c) for c in data["narration"]]
    return frames, chunks


def _save_cache(
    claim_id: str, frames: list[KeyFrame], chunks: list[NarrationChunk]
) -> None:
    p = _cache_path(claim_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "frames": [asdict(f) for f in frames],
        "narration": [asdict(c) for c in chunks],
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _find_video(claim_id: str) -> Path:
    candidates = [
        Path(config.OUTPUT_DIR) / claim_id / "video.mp4",
        Path("real-video.mp4"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(
        f"No cached ingest data and no source video found. "
        f"Tried: {[str(c) for c in candidates]}"
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python detect_inventory.py <claim_id> [incident_context]")
        sys.exit(1)

    claim_id = sys.argv[1]
    incident_context = sys.argv[2] if len(sys.argv) > 2 else None

    cached = _load_cache(claim_id)
    if cached is None:
        from ingest_video import ingest_video
        video_path = _find_video(claim_id)
        print(f"[main] no cache found; running ingest_video on {video_path}")
        frames, chunks = ingest_video(str(video_path), claim_id)
        _save_cache(claim_id, frames, chunks)
        print(f"[main] cached {len(frames)} frames + {len(chunks)} chunks")
    else:
        frames, chunks = cached
        print(f"[main] loaded cache: {len(frames)} frames + {len(chunks)} chunks")

    print("[main] resetting vector store collections for this claim")
    vector_store.reset_claim(claim_id)
    vector_store.add_frames(claim_id, frames)
    vector_store.add_narration(claim_id, chunks)

    print(f"[main] running detect_inventory (incident={incident_context!r})")
    items = detect_inventory(frames, chunks, claim_id, incident_context)

    print("\n========= INVENTORY =========")
    for it in items:
        print(f"\n[{it.item_id}] {it.name}")
        print(f"  category:         {it.category}")
        print(f"  description:      {it.description}")
        print(f"  damage:           {it.damage_observed}")
        print(f"  confidence:       {it.confidence:.2f}")
        print(f"  brand_recognized: {it.brand_recognized}")
        print(f"  seen:             {it.first_seen_sec:.1f}s -> {it.last_seen_sec:.1f}s")
        print(f"  source_frames:    {it.source_frame_ids}")
        print(f"  source_chunks:    {it.source_narration_ids}")

    out_path = Path(config.OUTPUT_DIR) / claim_id / "inventory.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([asdict(it) for it in items], f, indent=2)
    print(f"\n[main] wrote {out_path}")
