"""Policy ingestion module.

Parses a claimant's insurance policy PDF and produces a list of
`PolicySection` chunks with embeddings, ready to be indexed for
retrieval against detected inventory items.

Strategy:
1. Pull text per-page via pypdf and join with double newlines.
2. Try a sequence of heading regexes (SECTION X, ARTICLE/PART X,
   N.M Title). Use the first pattern that fires at least 3 times
   to slice the document into titled sections.
3. Clean titles (strip dot-leaders + page numbers).
4. Filter out low-signal sections (TOC entries, blank inventory
   forms, very short bodies) and de-duplicate by normalized title,
   preferring the variant with the longer body.
5. Embed each surviving section with the shared text encoder.
6. If no headings hit, fall back to fixed ~400-word chunks with
   50-word overlap.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from pypdf import PdfReader

from embeddings import embed_text
from schemas import PolicySection

HEADING_PATTERNS: list[str] = [
    # SECTION I  /  SECTION 4. - Property Coverage
    r"(?im)^\s*SECTION\s+([IVX\d]+[\.\:]?)\s*[-\u2013\u2014]?\s*(.*?)$",
    # ARTICLE 5  /  PART II — Definitions
    r"(?im)^\s*(?:ARTICLE|PART)\s+([IVX\d]+[\.\:]?)\s*[-\u2013\u2014]?\s*(.*?)$",
    # 4.2 Additional Living Expenses
    r"(?m)^\s*(\d+\.\d+)\s+(.+?)$",
]

CHUNK_WORDS: int = 400
CHUNK_OVERLAP: int = 50
MIN_HEADING_MATCHES: int = 3

MIN_BODY_CHARS: int = 200
MIN_UNIQUE_WORDS: int = 30
TOC_WHITESPACE_DOT_RATIO: float = 0.40
TITLE_DEDUP_PREFIX: int = 40
_TOC_CHARS = frozenset(" .\t\n")


def _extract_text(pdf_path: str) -> str:
    try:
        reader = PdfReader(pdf_path)
    except Exception as e:
        print(f"[ingest_policy] failed to open PDF: {e}")
        raise

    pages: list[str] = []
    for i, page in enumerate(reader.pages):
        try:
            pages.append(page.extract_text() or "")
        except Exception as e:
            print(f"[ingest_policy] page {i} extract failed: {e}")
            pages.append("")
    return "\n\n".join(pages)


def _slugify(s: str, max_len: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return s[:max_len] if s else "untitled"


def _clean_number(num: str) -> str:
    """Normalize a captured heading number for use in an id (e.g. '4.2.', 'I:' -> '4.2', 'i')."""
    return num.strip().rstrip(".:").lower()


def _clean_title(title: str) -> str:
    """Strip TOC dot-leaders, trailing page numbers, and collapse whitespace."""
    title = re.sub(r"\s*\.{2,}.*$", "", title)
    title = re.sub(r"\s+\d+\s*$", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def _normalize_title_for_dedup(title: str) -> str:
    """Lowercased, alphanumeric-only, first N chars — used as a dedup key."""
    return re.sub(r"[^a-z0-9]", "", title.lower())[:TITLE_DEDUP_PREFIX]


def _drop_reason(section: PolicySection) -> str | None:
    """Return a drop bucket name, or None if the section should be kept.

    Priority: inventory_form > toc_like > too_short, so the most
    specific signal wins in the per-section log line.
    """
    if "INVENTORY" in section.title.upper():
        return "inventory_form"

    body = section.text
    if body:
        ratio = sum(1 for c in body if c in _TOC_CHARS) / len(body)
        if ratio >= TOC_WHITESPACE_DOT_RATIO:
            return "toc_like"

    if len(body) < MIN_BODY_CHARS:
        return "too_short"

    unique_words = set(re.sub(r"[^\w\s]", " ", body.lower()).split())
    if len(unique_words) < MIN_UNIQUE_WORDS:
        return "too_short"

    return None


def _split_by_heading(text: str, pattern: str) -> list[PolicySection] | None:
    """Slice `text` on heading matches. Sections returned WITHOUT embeddings;
    embedding happens later, only on survivors."""
    matches = list(re.finditer(pattern, text))
    if len(matches) < MIN_HEADING_MATCHES:
        return None

    sections: list[PolicySection] = []
    seen_ids: set[str] = set()

    for i, m in enumerate(matches):
        groups = [g for g in m.groups() if g is not None]
        if len(groups) >= 2:
            number_raw = groups[0].strip().rstrip(".:")
            title_raw = groups[1]
        elif len(groups) == 1:
            number_raw = ""
            title_raw = groups[0]
        else:
            number_raw = ""
            title_raw = m.group(0)

        title = _clean_title(title_raw)

        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()

        heading_text = (f"{number_raw} {title}".strip() if number_raw else title) or "Untitled"

        base_id = (
            f"section_{_clean_number(number_raw)}"
            if number_raw
            else f"section_{_slugify(heading_text)}"
        )
        sec_id = base_id
        suffix = 2
        while sec_id in seen_ids:
            sec_id = f"{base_id}_{suffix}"
            suffix += 1
        seen_ids.add(sec_id)

        sections.append(
            PolicySection(
                section_id=sec_id,
                title=heading_text,
                text=body,
                embedding=None,
            )
        )

    return sections


def _filter_and_dedupe(
    sections: list[PolicySection],
) -> tuple[list[PolicySection], dict[str, int]]:
    """Drop low-signal sections and collapse duplicate titles."""
    counts = {
        "detected": len(sections),
        "too_short": 0,
        "inventory_form": 0,
        "toc_like": 0,
        "duplicate": 0,
    }

    surviving: list[PolicySection] = []
    for s in sections:
        reason = _drop_reason(s)
        if reason is None:
            surviving.append(s)
        else:
            counts[reason] += 1

    by_norm_title: dict[str, PolicySection] = {}
    for s in surviving:
        key = _normalize_title_for_dedup(s.title)
        existing = by_norm_title.get(key)
        if existing is None:
            by_norm_title[key] = s
        else:
            counts["duplicate"] += 1
            if len(s.text) > len(existing.text):
                by_norm_title[key] = s

    kept = list(by_norm_title.values())
    counts["kept"] = len(kept)
    return kept, counts


def _chunk_fallback(text: str) -> list[PolicySection]:
    words = text.split()
    if not words:
        return []

    sections: list[PolicySection] = []
    stride = CHUNK_WORDS - CHUNK_OVERLAP
    i = 0
    idx = 0
    while i < len(words):
        chunk_words = words[i : i + CHUNK_WORDS]
        chunk_text = " ".join(chunk_words).strip()
        sections.append(
            PolicySection(
                section_id=f"chunk_{idx:04d}",
                title="Policy Excerpt",
                text=chunk_text,
                embedding=embed_text(chunk_text) if chunk_text else None,
            )
        )
        idx += 1
        if i + CHUNK_WORDS >= len(words):
            break
        i += stride
    return sections


def _print_filter_report(counts: dict[str, int]) -> None:
    print(f"[ingest_policy] Sections detected: {counts['detected']}")
    print(f"[ingest_policy] Sections dropped (too short): {counts['too_short']}")
    print(f"[ingest_policy] Sections dropped (inventory form): {counts['inventory_form']}")
    print(f"[ingest_policy] Sections dropped (TOC-like): {counts['toc_like']}")
    print(f"[ingest_policy] Sections dropped (duplicate): {counts['duplicate']}")
    print(f"[ingest_policy] Sections kept: {counts['kept']}")


def ingest_policy(pdf_path: str) -> list[PolicySection]:
    """Parse a policy PDF into embedded `PolicySection`s.

    Args:
        pdf_path: Path to the policy PDF on disk.

    Returns:
        List of `PolicySection` objects, each with a populated embedding.
    """
    if not Path(pdf_path).is_file():
        raise FileNotFoundError(f"Policy PDF not found: {pdf_path}")

    text = _extract_text(pdf_path)
    if not text.strip():
        print("[ingest_policy] WARNING: no text extracted from PDF")
        return []

    for pattern in HEADING_PATTERNS:
        result = _split_by_heading(text, pattern)
        if result is None:
            continue

        kept, counts = _filter_and_dedupe(result)
        _print_filter_report(counts)

        for s in kept:
            s.embedding = embed_text(s.text)
        return kept

    return _chunk_fallback(text)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ingest_policy.py <pdf_path>")
        sys.exit(1)

    pdf_arg = sys.argv[1]
    sections = ingest_policy(pdf_arg)

    print(f"Sections: {len(sections)}")
    for s in sections[:3]:
        preview = re.sub(r"\s+", " ", s.text)[:100]
        print(f"  - {s.section_id} | {s.title!r}")
        print(f"      {preview!r}")
