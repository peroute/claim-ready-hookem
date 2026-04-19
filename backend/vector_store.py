"""Vector store wrapper around ChromaDB.

Manages three per-claim collections — frames (CLIP 512-dim), narration
(MiniLM 384-dim), and policy (MiniLM 384-dim) — with add/search
helpers used by detect_inventory, search_policy, and the pipeline
orchestrator.

All collections live in a single PersistentClient rooted at
`config.CHROMA_DIR` and use cosine distance.
"""

from __future__ import annotations

from typing import Any, Literal

import chromadb

import config
from embeddings import embed_text
from schemas import KeyFrame, NarrationChunk, PolicySection

CollectionKind = Literal["frames", "narration", "policy"]

_client: Any | None = None


def _get_client() -> Any:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=config.CHROMA_DIR)
    return _client


def _collection_name(claim_id: str, kind: CollectionKind) -> str:
    return f"{kind}_{claim_id}"


def get_or_create_collection(claim_id: str, kind: CollectionKind) -> Any:
    """Fetch (or create on first call) the per-claim collection of `kind`."""
    client = _get_client()
    return client.get_or_create_collection(
        name=_collection_name(claim_id, kind),
        metadata={"hnsw:space": "cosine"},
    )


def add_frames(claim_id: str, frames: list[KeyFrame]) -> None:
    """Index keyframes (CLIP embeddings + timestamp/path metadata)."""
    coll = get_or_create_collection(claim_id, "frames")
    ids: list[str] = []
    embeddings: list[list[float]] = []
    metadatas: list[dict[str, Any]] = []
    for f in frames:
        if f.embedding is None:
            print(f"[vector_store] WARNING: frame {f.frame_id} has no embedding; skipping")
            continue
        ids.append(f.frame_id)
        embeddings.append(f.embedding)
        metadatas.append(
            {"timestamp_sec": f.timestamp_sec, "image_path": f.image_path}
        )
    if not ids:
        return
    coll.add(ids=ids, embeddings=embeddings, metadatas=metadatas)


def add_narration(claim_id: str, chunks: list[NarrationChunk]) -> None:
    """Index narration chunks (text embeddings + time-window metadata)."""
    coll = get_or_create_collection(claim_id, "narration")
    ids: list[str] = []
    embeddings: list[list[float]] = []
    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []
    for c in chunks:
        if c.embedding is None:
            print(f"[vector_store] WARNING: chunk {c.chunk_id} has no embedding; skipping")
            continue
        ids.append(c.chunk_id)
        embeddings.append(c.embedding)
        documents.append(c.text)
        metadatas.append({"start_sec": c.start_sec, "end_sec": c.end_sec})
    if not ids:
        return
    coll.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)


def add_policy(claim_id: str, sections: list[PolicySection]) -> None:
    """Index policy sections (text embeddings + title metadata)."""
    coll = get_or_create_collection(claim_id, "policy")
    ids: list[str] = []
    embeddings: list[list[float]] = []
    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []
    for s in sections:
        if s.embedding is None:
            print(f"[vector_store] WARNING: section {s.section_id} has no embedding; skipping")
            continue
        ids.append(s.section_id)
        embeddings.append(s.embedding)
        documents.append(s.text)
        metadatas.append({"title": s.title})
    if not ids:
        return
    coll.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)


def search_policy(claim_id: str, query_text: str, top_k: int = 3) -> list[dict]:
    """Semantic search over policy sections; returns top-k by cosine distance ascending."""
    coll = get_or_create_collection(claim_id, "policy")
    query_emb = embed_text(query_text)
    res = coll.query(
        query_embeddings=[query_emb],
        n_results=top_k,
        include=["metadatas", "documents", "distances"],
    )
    ids = res["ids"][0]
    metas = res["metadatas"][0]
    docs = res["documents"][0]
    dists = res["distances"][0]
    out: list[dict] = []
    for i, _id in enumerate(ids):
        m = metas[i] or {}
        out.append(
            {
                "section_id": _id,
                "title": m.get("title", ""),
                "text": (docs[i] if i < len(docs) else "") or "",
                "distance": float(dists[i]),
            }
        )
    out.sort(key=lambda r: r["distance"])
    return out


def search_narration_by_time(
    claim_id: str, start_sec: float, end_sec: float
) -> list[dict]:
    """Return narration chunks whose [start_sec, end_sec] overlaps the requested window."""
    coll = get_or_create_collection(claim_id, "narration")
    res = coll.get(
        where={
            "$and": [
                {"start_sec": {"$lte": end_sec}},
                {"end_sec": {"$gte": start_sec}},
            ]
        },
        include=["metadatas", "documents"],
    )
    ids = res.get("ids", []) or []
    metas = res.get("metadatas", []) or []
    docs = res.get("documents", []) or []
    out: list[dict] = []
    for i, _id in enumerate(ids):
        m = metas[i] or {}
        out.append(
            {
                "chunk_id": _id,
                "text": (docs[i] if i < len(docs) else "") or "",
                "start_sec": float(m.get("start_sec", 0.0)),
                "end_sec": float(m.get("end_sec", 0.0)),
            }
        )
    out.sort(key=lambda r: r["start_sec"])
    return out


def search_frames_by_time(
    claim_id: str, start_sec: float, end_sec: float
) -> list[dict]:
    """Return frames whose timestamp_sec falls in [start_sec, end_sec]."""
    coll = get_or_create_collection(claim_id, "frames")
    res = coll.get(
        where={
            "$and": [
                {"timestamp_sec": {"$gte": start_sec}},
                {"timestamp_sec": {"$lte": end_sec}},
            ]
        },
        include=["metadatas"],
    )
    ids = res.get("ids", []) or []
    metas = res.get("metadatas", []) or []
    out: list[dict] = []
    for i, _id in enumerate(ids):
        m = metas[i] or {}
        out.append(
            {
                "frame_id": _id,
                "timestamp_sec": float(m.get("timestamp_sec", 0.0)),
                "image_path": m.get("image_path", ""),
            }
        )
    out.sort(key=lambda r: r["timestamp_sec"])
    return out


def reset_claim(claim_id: str) -> None:
    """Delete all three collections for `claim_id`. Safe to call when nothing exists."""
    client = _get_client()
    for kind in ("frames", "narration", "policy"):
        name = _collection_name(claim_id, kind)
        try:
            client.delete_collection(name=name)
        except Exception:
            pass


if __name__ == "__main__":
    import math
    import random

    claim_id = "vstore_test"

    def _rand_unit_vec(n: int) -> list[float]:
        v = [random.random() - 0.5 for _ in range(n)]
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    print("== reset_claim (initial) ==")
    reset_claim(claim_id)
    print("ok")

    print("\n== add_policy + search_policy ==")
    fake_sections = [
        PolicySection(
            section_id="sec_a",
            title="Personal Property Coverage",
            text="We cover personal property up to your limit.",
            embedding=_rand_unit_vec(384),
        ),
        PolicySection(
            section_id="sec_b",
            title="Flood Exclusion",
            text="Flood damage is excluded unless you have a flood policy.",
            embedding=_rand_unit_vec(384),
        ),
        PolicySection(
            section_id="sec_c",
            title="Replacement Cost",
            text="Replacement cost coverage applies to electronics.",
            embedding=_rand_unit_vec(384),
        ),
    ]
    add_policy(claim_id, fake_sections)
    results = search_policy(claim_id, "what is covered for water damage?", top_k=3)
    for r in results:
        print(f"  {r['section_id']}  d={r['distance']:.4f}  {r['title']!r}")

    print("\n== add_narration + search_narration_by_time(0.0, 6.0) ==")
    fake_chunks = [
        NarrationChunk(
            chunk_id="c0", start_sec=0.0, end_sec=5.0,
            text="walking into the living room", embedding=_rand_unit_vec(384),
        ),
        NarrationChunk(
            chunk_id="c1", start_sec=4.0, end_sec=10.0,
            text="here is the damaged tv", embedding=_rand_unit_vec(384),
        ),
        NarrationChunk(
            chunk_id="c2", start_sec=12.0, end_sec=18.0,
            text="moving to the kitchen", embedding=_rand_unit_vec(384),
        ),
    ]
    add_narration(claim_id, fake_chunks)
    overlapping = search_narration_by_time(claim_id, 0.0, 6.0)
    print(f"  overlaps in [0,6]: {[r['chunk_id'] for r in overlapping]}")
    expected = ["c0", "c1"]
    actual = [r["chunk_id"] for r in overlapping]
    assert actual == expected, f"expected {expected}, got {actual}"
    print("  assertion passed: c0 and c1 returned, c2 correctly excluded")

    print("\n== reset_claim (cleanup) ==")
    reset_claim(claim_id)
    print("ok")
