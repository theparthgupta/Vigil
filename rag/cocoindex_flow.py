"""
CocoIndex declarative flow for the Vigil regulatory corpus (Phase 9A).

Replaces the manual Chroma ingest with a declarative CocoIndex flow that
targets pgvector. CocoIndex tracks source-file lineage and re-embeds ONLY
changed/new files on each `update()` (and removes orphaned chunks) — no
manual diffing.

The PDF extraction + section-boundary chunking is the EXACT Phase-3 logic,
reused from rag/ingest.py (extract logic, _SECTION_RE / _INLINE_RULE_RE
run-on handling, make_chunks). CocoIndex only orchestrates and embeds.

Flow:  regs/*.pdf  →  chunk_pdf_file (custom op)  →  EmbedText(OpenAI)
                  →  collect  →  Postgres table "vigil_regulatory_chunks"

Pinned to cocoindex==0.3.39 (the 1.0 line removed this DSL).

NOTE: this module intentionally does NOT use `from __future__ import annotations`
— CocoIndex's op analyzer inspects raw annotation objects and cannot resolve
stringized annotations, so `bytes`/`str`/`int` must remain real types here.
"""

import dataclasses
import io
import os
import sys
from pathlib import Path
from typing import Optional

import cocoindex
from dotenv import load_dotenv
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).parent.parent))

# Reuse the EXACT Phase-3 extraction + chunking logic. Do not reimplement.
from rag.ingest import _DOCS, _REGS_DIR, build_corpus, make_chunks

_TABLE_NAME = "vigil_regulatory_chunks"
_DOC_BY_FILENAME = {d["filename"]: d for d in _DOCS}

# Guard so cocoindex.init() runs at most once per process.
_INITIALISED = False


# ── Chunk row type (the columns of the target table, minus embedding) ─────────

@dataclasses.dataclass
class RegChunk:
    chunk_id: str
    source: str
    section: str
    page: int
    text: str


def _extract_pages_from_bytes(
    content: bytes, max_pages: Optional[int]
) -> list[tuple[int, str]]:
    """Mirror rag.ingest.extract_pages, but from in-memory PDF bytes."""
    reader = PdfReader(io.BytesIO(content))
    pages = reader.pages[:max_pages] if max_pages else reader.pages
    out: list[tuple[int, str]] = []
    for i, page in enumerate(pages):
        text = page.extract_text() or ""
        if text.strip():
            out.append((i + 1, text))
    return out


@cocoindex.op.function()
def chunk_pdf_file(content: bytes, filename: str) -> list[RegChunk]:
    """Extract + section-chunk one PDF using the Phase-3 logic. Returns a table."""
    meta = _DOC_BY_FILENAME.get(filename, {"citation": filename, "max_pages": None})
    pages = _extract_pages_from_bytes(content, meta["max_pages"])
    corpus, page_map = build_corpus(pages)
    chunks = make_chunks(corpus, page_map, meta["citation"], filename)
    return [
        RegChunk(
            chunk_id=c["id"],
            source=c["source"],
            section=c["section"],
            page=c["page"],
            text=c["text"],
        )
        for c in chunks
    ]


@cocoindex.flow_def(name="VigilRegulatoryCorpus")
def vigil_regulatory_corpus(
    flow_builder: cocoindex.FlowBuilder, data_scope: cocoindex.DataScope
) -> None:
    """Embed all regs/*.pdf into pgvector, incrementally maintained."""
    data_scope["documents"] = flow_builder.add_source(
        cocoindex.sources.LocalFile(
            path=str(_REGS_DIR), binary=True, included_patterns=["*.pdf"]
        )
    )

    collector = data_scope.add_collector()

    with data_scope["documents"].row() as doc:
        doc["chunks"] = flow_builder.transform(
            chunk_pdf_file, doc["content"], doc["filename"]
        )
        with doc["chunks"].row() as chunk:
            chunk["embedding"] = chunk["text"].transform(
                cocoindex.functions.EmbedText(
                    api_type=cocoindex.llm.LlmApiType.OPENAI,
                    model="text-embedding-3-small",
                )
            )
            collector.collect(
                chunk_id=chunk["chunk_id"],
                source=chunk["source"],
                section=chunk["section"],
                page=chunk["page"],
                text=chunk["text"],
                embedding=chunk["embedding"],
            )

    collector.export(
        _TABLE_NAME,
        cocoindex.targets.Postgres(table_name=_TABLE_NAME),
        primary_key_fields=["chunk_id"],
        vector_indexes=[
            cocoindex.VectorIndexDef(
                field_name="embedding",
                metric=cocoindex.VectorSimilarityMetric.COSINE_SIMILARITY,
            )
        ],
    )


def init_cocoindex() -> None:
    """Initialise the CocoIndex engine against the vigil database (idempotent)."""
    global _INITIALISED
    if _INITIALISED:
        return
    load_dotenv()
    url = os.environ["DATABASE_URL"]
    cocoindex.init(
        cocoindex.Settings(database=cocoindex.DatabaseConnectionSpec(url=url))
    )
    _INITIALISED = True
