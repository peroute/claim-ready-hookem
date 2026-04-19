"""End-to-end claim-ready pipeline orchestrator.

Single entry point that runs every stage in sequence:

    ingest_video → ingest_policy → vector_store
                 → detect_inventory → search_policy → generate_packet

Designed to be called both from `api.py` (HTTP) and from the CLI
(`__main__` block at the bottom). Stage progress is reported through
an optional callback so the API layer can stream updates to the
frontend.

Each stage is wrapped in try/except: a failure emits a final
`PipelineProgress(stage="error", percent=-1, ...)` and re-raises so
the caller can react.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

import config
import vector_store
from detect_inventory import detect_inventory
from generate_packet import generate_packet
from ingest_policy import ingest_policy
from ingest_video import ingest_video
from schemas import ClaimPacket, InventoryItem
from search_policy import search_policy


@dataclass
class PipelineProgress:
    stage: str       # e.g. "ingesting_video", "complete", "error"
    percent: float   # 0-100, or -1 for errors
    message: str     # human-readable status
    claim_id: str


ProgressCb = Callable[[PipelineProgress], None]


def _emit(cb: Optional[ProgressCb], p: PipelineProgress) -> None:
    if cb is not None:
        cb(p)


def _save_inventory(items: list[InventoryItem], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(it) for it in items], f, indent=2)


def _save_packet_meta(packet: ClaimPacket, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(packet), f, indent=2)


def run_pipeline(
    claim_id: str,
    video_path: str,
    policy_path: str,
    intake: dict,
    progress_callback: Optional[ProgressCb] = None,
) -> ClaimPacket:
    """Execute every pipeline stage and return the rendered ClaimPacket.

    Args:
        claim_id: scopes outputs and vector-store collections.
        video_path: source walkthrough video.
        policy_path: source policy PDF.
        intake: dict with `incident_date`, `cause`, `location`,
            `claimant_name` (used for the incident summary, FNOL
            letter, and packet cover page).
        progress_callback: optional sink for `PipelineProgress` events.

    Returns:
        The fully populated `ClaimPacket` (including `pdf_path`).

    Raises:
        Re-raises any exception from a stage after emitting an error
        progress event.
    """
    out_dir = Path(config.OUTPUT_DIR) / claim_id

    try:
        # ---------- 1. ingest video ----------
        _emit(progress_callback, PipelineProgress(
            stage="ingesting_video",
            percent=5.0,
            message="Extracting frames and transcribing audio...",
            claim_id=claim_id,
        ))
        frames, narration = ingest_video(video_path, claim_id)

        # ---------- 2. ingest policy ----------
        _emit(progress_callback, PipelineProgress(
            stage="ingesting_policy",
            percent=25.0,
            message="Parsing policy document...",
            claim_id=claim_id,
        ))
        policy_sections = ingest_policy(policy_path)

        # ---------- 3. build vector index ----------
        _emit(progress_callback, PipelineProgress(
            stage="building_index",
            percent=35.0,
            message="Indexing for semantic search...",
            claim_id=claim_id,
        ))
        vector_store.reset_claim(claim_id)
        vector_store.add_frames(claim_id, frames)
        vector_store.add_narration(claim_id, narration)
        vector_store.add_policy(claim_id, policy_sections)

        # ---------- 4. detect inventory ----------
        _emit(progress_callback, PipelineProgress(
            stage="detecting_inventory",
            percent=45.0,
            message="Detecting damaged items with Gemini Vision...",
            claim_id=claim_id,
        ))
        items = detect_inventory(
            frames, narration, claim_id,
            incident_context=intake.get("cause"),
        )
        _save_inventory(items, out_dir / "inventory.json")

        # ---------- 5. policy citations ----------
        _emit(progress_callback, PipelineProgress(
            stage="searching_policy",
            percent=80.0,
            message="Matching items to policy coverage...",
            claim_id=claim_id,
        ))
        items = search_policy(claim_id, items)
        _save_inventory(items, out_dir / "inventory_with_citations.json")

        # ---------- 6. render packet ----------
        _emit(progress_callback, PipelineProgress(
            stage="generating_packet",
            percent=90.0,
            message="Rendering claim packet PDF...",
            claim_id=claim_id,
        ))
        packet = generate_packet(
            claim_id=claim_id,
            items=items,
            policy_sections=policy_sections,
            intake=intake,
            video_source_path=video_path,
            policy_source_path=policy_path,
            narration=narration,
            frame_count=len(frames),
        )

        # ---------- 7. persist packet metadata ----------
        _save_packet_meta(packet, out_dir / "packet.json")

        # ---------- 8. final ----------
        _emit(progress_callback, PipelineProgress(
            stage="complete",
            percent=100.0,
            message="Claim packet ready",
            claim_id=claim_id,
        ))
        return packet

    except Exception as e:
        _emit(progress_callback, PipelineProgress(
            stage="error",
            percent=-1.0,
            message=str(e),
            claim_id=claim_id,
        ))
        raise


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _cli_progress(p: PipelineProgress) -> None:
    if p.percent < 0:
        print(f"[ERROR] {p.stage}: {p.message}")
    else:
        print(f"[{p.percent:5.1f}%] {p.stage}: {p.message}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python pipeline.py <claim_id> <video_path> <policy_path>")
        sys.exit(1)

    claim_id = sys.argv[1]
    video_path = sys.argv[2]
    policy_path = sys.argv[3]

    intake = {
        "incident_date": "April 18, 2026",
        "cause": "Water damage from pipe burst",
        "location": "Living room and bedroom",
        "claimant_name": "Hedi Bouassida",
    }

    packet = run_pipeline(
        claim_id=claim_id,
        video_path=video_path,
        policy_path=policy_path,
        intake=intake,
        progress_callback=_cli_progress,
    )

    print(f"\nFinal PDF: {packet.pdf_path}")
    print(f"Items:     {len(packet.items)}")
    print(f"Cited:     {len(packet.policy_sections_cited)} policy section(s)")
