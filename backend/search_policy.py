"""Policy search module.

For each detected `InventoryItem`, retrieves the most relevant
`PolicySection`s from the per-claim policy collection in the vector
store and attaches their identifiers as `policy_citations` so the
final packet can justify coverage.

The query for each item emphasises both the damage description and
the item type/category, which empirically matches policy language
("damage to electronics", "personal property coverage", ...) better
than the item name alone.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import config
import vector_store
from schemas import InventoryItem


GENERIC_FALLBACK_TOP_K: int = 1


def _build_query(item: InventoryItem) -> str:
    damage = item.damage_observed.strip() or "damage"
    return f"{item.category} damage: {item.name}. {damage}"


def _generic_query(item: InventoryItem) -> str:
    return f"personal property {item.category}"


def search_policy(
    claim_id: str,
    items: list[InventoryItem],
    top_k: int = 2,
    similarity_threshold: float = 0.55,
) -> list[InventoryItem]:
    """Annotate each item with relevant policy section IDs.

    Args:
        claim_id: scopes the policy collection in the vector store.
        items: inventory items produced by detect_inventory.
        top_k: max sections to consider per item.
        similarity_threshold: cosine *distance* cutoff (lower = more
            similar). Sections with distance > threshold are dropped.

    Returns:
        The same `items` list with `policy_citations` populated.
        Items that have no section under the threshold fall back to a
        generic query so every item gets at least one citation.
    """
    for item in items:
        primary_query = _build_query(item)
        results = vector_store.search_policy(claim_id, primary_query, top_k=top_k)

        kept = [r for r in results if r.get("distance", 1.0) <= similarity_threshold]

        if not kept:
            fallback_query = _generic_query(item)
            fallback = vector_store.search_policy(
                claim_id, fallback_query, top_k=GENERIC_FALLBACK_TOP_K
            )
            kept = fallback[:GENERIC_FALLBACK_TOP_K]
            source = "fallback"
        else:
            source = "primary"

        item.policy_citations = [r["section_id"] for r in kept]

        kept_summary = ", ".join(
            f"{r['section_id']}@{r.get('distance', float('nan')):.3f}" for r in kept
        ) or "(none)"
        print(
            f"[search_policy] {item.item_id} {item.name!r} "
            f"[{source}] -> citations: [{kept_summary}]"
        )

    return items


# ---------------------------------------------------------------------------
# __main__: load inventory.json, ingest policy, run, save annotated items
# ---------------------------------------------------------------------------

def _load_inventory(path: Path) -> list[InventoryItem]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [InventoryItem(**d) for d in raw]


def _save_inventory(items: list[InventoryItem], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(it) for it in items], f, indent=2)


def _find_policy_pdf(claim_id: str) -> Path:
    candidates = [
        Path(config.OUTPUT_DIR) / claim_id / "policy.pdf",
        Path("demo_policy.pdf"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(
        f"No policy PDF found. Tried: {[str(c) for c in candidates]}"
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python search_policy.py <claim_id>")
        sys.exit(1)

    claim_id = sys.argv[1]
    inv_path = Path(config.OUTPUT_DIR) / claim_id / "inventory.json"
    if not inv_path.is_file():
        print(f"[main] missing {inv_path}; run detect_inventory first")
        sys.exit(1)

    pdf_path = _find_policy_pdf(claim_id)
    print(f"[main] ingesting policy: {pdf_path}")
    from ingest_policy import ingest_policy
    sections = ingest_policy(str(pdf_path))
    print(f"[main] policy sections: {len(sections)}")

    print(f"[main] (re)loading policy collection for claim={claim_id!r}")
    try:
        vector_store._get_client().delete_collection(f"policy_{claim_id}")  # type: ignore[attr-defined]
    except Exception:
        pass
    vector_store.add_policy(claim_id, sections)

    items = _load_inventory(inv_path)
    print(f"[main] loaded {len(items)} inventory items from {inv_path}")

    annotated = search_policy(claim_id, items)

    out_path = Path(config.OUTPUT_DIR) / claim_id / "inventory_with_citations.json"
    _save_inventory(annotated, out_path)

    print("\n========= CITATION SUMMARY =========")
    section_lookup: dict[str, str] = {s.section_id: s.title for s in sections}
    for it in annotated:
        print(f"\n[{it.item_id}] {it.name}  ({it.category})")
        if not it.policy_citations:
            print("  (no citations)")
            continue
        for sid in it.policy_citations:
            title = section_lookup.get(sid, "<unknown section>")
            print(f"  - {sid}: {title}")

    print(f"\n[main] wrote {out_path}")
