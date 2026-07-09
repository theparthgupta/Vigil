"""
RAG ingest for Vigil.

Loads regulatory PDFs from regs/, chunks by section boundaries (not fixed size),
embeds with OpenAI text-embedding-3-small, persists in Chroma.

Usage:
    python rag/ingest.py          # incremental (skip already-stored chunks)
    python rag/ingest.py --reset  # wipe collection and rebuild from scratch
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

_REGS_DIR = Path(__file__).parent.parent / "regs"
_CHROMA_DIR = Path(__file__).parent / "chroma_db"
_COLLECTION = "vigil_regs"

# ── Document registry ─────────────────────────────────────────────────────────
# max_pages: None = all pages. For FIU-IND, pages 1-10 are TOC, 11-50 substantive.
_DOCS: list[dict] = [
    dict(
        filename="A2003-15.pdf",
        citation="PMLA 2002 (Act No. 15 of 2003)",
        max_pages=None,
    ),
    dict(
        filename="169MD.pdf",
        citation="RBI KYC Master Directions 2025 (DOR.AML.REC.No.88/14.01.002/2025-26)",
        max_pages=None,
    ),
    dict(
        filename="Reporting_Format.pdf",
        citation="FIU-IND Reporting Format v1.14 (FINnet 2.0)",
        max_pages=23,  # pages 1-10 = TOC; 11-23 = intro + format overview; 24+ = schema tables (noise)
    ),
    dict(
        filename="2024_APG_Typologies_Report.pdf",
        citation="APG Yearly Typologies Report 2024",
        max_pages=None,
    ),
    dict(
        filename="PMLA_Rules.pdf",
        citation="PMLA (Maintenance of Records) Rules, 2005 (G.S.R. 444(E))",
        max_pages=None,
    ),
]

# ── Section boundary patterns ─────────────────────────────────────────────────
# Detect start of a new legal/regulatory section. Ordered: most specific first.
# All patterns anchored to start-of-line (re.MULTILINE).
_SECTION_PATTERNS = [
    # PMLA all-caps chapters: "CHAPTER I", "CHAPTER IV"
    r"CHAPTER\s+[IVXLCD]+\b",
    # RBI chapter with dash/en-dash: "Chapter I –", "Chapter IV —"
    r"Chapter\s+[IVXLCD\d]+\s*[–—\-]",
    # PMLA/RBI numbered sections with optional letter suffix:
    # "12.", "12A.", "12AA.", "11A."  followed by a capital-word
    r"\d{1,3}[A-Z]{0,2}\.\s+[A-Z][a-z]",
    # RBI lettered subsections: "A. Short Title", "B. Applicability"
    r"[A-Z]\.\s+[A-Z][a-z]",
    # APG/FIU decimal sections: "1.1 Overview", "2.4 India"  (max two levels deep)
    r"\d+\.\d{1,2}\s+[A-Z][a-z]",
    # APG top-level: "1 - MISUSE OF", "2 - MONEY LAUNDERING"
    r"\d+\s+[-–]\s+[A-Z]{3,}",
    # FIU plain-numbered section: "2 Guide to the new Reporting Formats"
    r"\d+\s+[A-Z][a-z]{3,}",
]

_SECTION_RE = re.compile(r"(?m)^[ \t]*(?:" + "|".join(_SECTION_PATTERNS) + r")")

# Some legal PDFs (e.g. the PMLA Rules gazette) extract as run-on text with no
# line breaks, so the line-anchored _SECTION_RE finds no boundaries. For those,
# detect numbered rule headers INLINE: end-of-clause punctuation, then "N." or
# "NA." immediately followed by a Capitalised word (e.g. "...crime.8.Furnishing").
_INLINE_RULE_RE = re.compile(r"(?<=[.\]\)])(\d{1,2}[A-Z]?\.\s?[A-Z][a-z]{3,})")
# Apply inline splitting only when newline density is very low (run-on extraction)
_RUNON_NEWLINE_RATIO = 0.005  # < 1 newline per 200 chars

# Chunk size targets (chars, not tokens — ~4 chars ≈ 1 token)
_MAX_CHUNK = 1600  # ~400 tokens — keep chunks focused
_MIN_CHUNK = 120  # drop anything shorter (TOC lines, page headers)
_OVERLAP = 150  # carry-over context between sub-chunks of the same section

# TOC line detection: lines with many dots (e.g. "Section 12 ......... 14")
_TOC_RE = re.compile(r"\.{4,}")
# Schema-table lines: very short lines dominate schema field-definition tables
# (e.g. "# Column Name Description Mandatory"). Filter chunks where >55% of
# lines are short — these are format tables, not regulatory prose.
_MAX_SHORT_LINE_RATIO = 0.55
_SHORT_LINE_THRESHOLD = 30  # chars


# ── PDF extraction ─────────────────────────────────────────────────────────────


def extract_pages(path: Path, max_pages: Optional[int]) -> list[tuple[int, str]]:
    """Return [(page_number, text), ...] for up to max_pages pages."""
    reader = PdfReader(str(path))
    pages = reader.pages[:max_pages] if max_pages else reader.pages
    out = []
    for i, page in enumerate(pages):
        text = page.extract_text() or ""
        if text.strip():
            out.append((i + 1, text))
    return out


def build_corpus(pages: list[tuple[int, str]]) -> tuple[str, list[tuple[int, int]]]:
    """
    Concatenate pages into one string and build a page-map.
    page_map: [(char_start_position, page_number), ...]
    """
    parts, page_map, pos = [], [], 0
    for page_num, text in pages:
        page_map.append((pos, page_num))
        parts.append(text)
        pos += len(text) + 1  # +1 for the joining \n
    return "\n".join(parts), page_map


def pos_to_page(pos: int, page_map: list[tuple[int, int]]) -> int:
    """Return the page number for a character position in the corpus."""
    page = 1
    for start, pnum in page_map:
        if start <= pos:
            page = pnum
        else:
            break
    return page


# ── Chunking ───────────────────────────────────────────────────────────────────


def _is_toc_line(line: str) -> bool:
    return bool(_TOC_RE.search(line)) or line.count("...") >= 2


def _first_section_header(text: str) -> str:
    """Return the first line that looks like a section header, else first line."""
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if _SECTION_RE.match(stripped):
            return stripped[:140]
        break
    # fallback: first non-empty, non-TOC line
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and not _is_toc_line(stripped):
            return stripped[:140]
    return "—"


def _split_by_paragraphs(text: str, max_chars: int, overlap: int) -> list[str]:
    """
    Split text at double-newlines (paragraph breaks). If a paragraph itself
    exceeds max_chars, split further at sentence boundaries.
    Carry overlap chars from the previous chunk.
    """
    if len(text) <= max_chars:
        return [text]

    paras = re.split(r"\n{2,}", text)
    chunks: list[str] = []
    buf = ""

    for para in paras:
        if len(buf) + len(para) + 2 <= max_chars:
            buf = (buf + "\n\n" + para).lstrip()
        else:
            if buf:
                chunks.append(buf)
                buf = buf[-overlap:].lstrip()  # carry-over

            if len(para) <= max_chars:
                buf = (buf + "\n\n" + para).lstrip() if buf else para
            else:
                # Para itself is oversized — split at sentences
                sentences = re.split(r"(?<=[.!?])\s+", para)
                for sent in sentences:
                    if len(buf) + len(sent) + 1 <= max_chars:
                        buf = (buf + " " + sent).strip()
                    else:
                        if buf:
                            chunks.append(buf)
                        buf = sent[:max_chars]

    if buf.strip():
        chunks.append(buf)

    return [c.strip() for c in chunks if c.strip()]


def make_chunks(
    corpus: str,
    page_map: list[tuple[int, int]],
    citation: str,
    filename: str,
) -> list[dict]:
    """
    Split the corpus at section boundaries, then sub-split large sections.
    Return list of chunk dicts with full metadata.
    """
    # Detect run-on extraction (no line breaks → line-anchored regex finds nothing)
    newline_ratio = corpus.count("\n") / max(len(corpus), 1)
    run_on = newline_ratio < _RUNON_NEWLINE_RATIO

    if run_on:
        boundaries = [m.start() for m in _INLINE_RULE_RE.finditer(corpus)]
    else:
        boundaries = [m.start() for m in _SECTION_RE.finditer(corpus)]
    if not boundaries:
        boundaries = [0]
    boundaries = sorted(set(boundaries))
    boundaries.append(len(corpus))

    chunks = []
    chunk_idx = 0

    for i, start in enumerate(boundaries[:-1]):
        end = boundaries[i + 1]
        section_text = corpus[start:end].strip()
        start_page = pos_to_page(start, page_map)
        if run_on:
            m = _INLINE_RULE_RE.match(section_text) or re.match(
                r"\d{1,2}[A-Z]?\.\s?[A-Z][a-z][^.]{3,60}", section_text
            )
            section_hdr = m.group().strip()[:140] if m else _first_section_header(section_text)
        else:
            section_hdr = _first_section_header(section_text)

        for part in _split_by_paragraphs(section_text, _MAX_CHUNK, _OVERLAP):
            # Drop TOC-dominated chunks and tiny stubs
            non_toc_lines = [ln for ln in part.split("\n") if not _is_toc_line(ln)]
            clean = " ".join(non_toc_lines).strip()
            if len(clean) < _MIN_CHUNK:
                continue

            # Drop schema-table chunks (field-definition tables with many short lines)
            all_lines = [ln for ln in part.split("\n") if ln.strip()]
            if all_lines:
                short_ratio = sum(
                    1 for ln in all_lines if len(ln.strip()) < _SHORT_LINE_THRESHOLD
                ) / len(all_lines)
                if short_ratio > _MAX_SHORT_LINE_RATIO:
                    continue

            chunk_id = f"{filename}_{chunk_idx:04d}"
            chunk_idx += 1
            chunks.append(
                {
                    "id": chunk_id,
                    "text": part,
                    "source": filename,
                    "citation": citation,
                    "section": section_hdr,
                    "page": start_page,
                }
            )

    return chunks


# ── Ingest ─────────────────────────────────────────────────────────────────────


def ingest_all(reset: bool = False) -> int:
    """Ingest all registered documents. Returns total new chunk count."""
    import chromadb
    from langchain_openai import OpenAIEmbeddings

    _CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(_CHROMA_DIR))

    if reset:
        try:
            client.delete_collection(_COLLECTION)
            print("Deleted existing collection.")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    existing_ids = set(collection.get(include=[])["ids"])
    print(f"Chunks already in store: {len(existing_ids)}")

    embedder = OpenAIEmbeddings(model="text-embedding-3-small")
    total_new = 0

    for doc in _DOCS:
        path = _REGS_DIR / doc["filename"]
        if not path.exists():
            print(f"  SKIP (not found): {doc['filename']}")
            continue

        print(f"\n{doc['filename']} ({doc['citation']})")
        pages = extract_pages(path, doc["max_pages"])
        corpus, page_map = build_corpus(pages)
        chunks = make_chunks(corpus, page_map, doc["citation"], doc["filename"])

        new = [c for c in chunks if c["id"] not in existing_ids]
        print(f"  {len(chunks)} chunks total, {len(new)} new to embed")

        if not new:
            continue

        BATCH = 100
        for i in range(0, len(new), BATCH):
            batch = new[i : i + BATCH]
            texts = [c["text"] for c in batch]
            embeddings = embedder.embed_documents(texts)

            collection.add(
                ids=[c["id"] for c in batch],
                documents=texts,
                embeddings=embeddings,  # type: ignore[arg-type]
                metadatas=[
                    {
                        "source": c["source"],
                        "citation": c["citation"],
                        "section": c["section"],
                        "page": c["page"],
                    }
                    for c in batch
                ],
            )
            total_new += len(batch)
            sys.stdout.write(f"  stored {min(i + BATCH, len(new))}/{len(new)}\r")
            sys.stdout.flush()
        print()

    print(f"\nDone. Total new chunks stored: {total_new}")
    return total_new


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reset", action="store_true", help="Delete and rebuild the Chroma collection"
    )
    args = parser.parse_args()
    ingest_all(reset=args.reset)
