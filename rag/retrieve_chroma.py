"""
RAG retrieve for Vigil — Chroma backend (LEGACY / FALLBACK).

Superseded by rag/retrieve_pg.py (CocoIndex + pgvector) in Phase 9A. Kept as a
tested fallback; not imported by the agent anymore.

Query the Chroma vector store; return passages with full citation metadata.

Usage:
    from rag.retrieve_chroma import retrieve
    results = retrieve("structuring threshold cash transaction India", k=5)
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

_CHROMA_DIR = Path(__file__).parent / "chroma_db"
_COLLECTION = "vigil_regs"

# Cached singletons. chromadb.PersistentClient is NOT safe to instantiate
# repeatedly / concurrently on the same path (tenant-connection errors under
# threads). Build once and reuse across all retrieve() calls.
_collection = None
_embedder = None
_init_lock = __import__("threading").Lock()


def _get_clients():
    global _collection, _embedder
    if _collection is None or _embedder is None:
        with _init_lock:
            if _collection is None or _embedder is None:
                import chromadb
                from langchain_openai import OpenAIEmbeddings

                client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
                _collection = client.get_collection(_COLLECTION)
                _embedder = OpenAIEmbeddings(model="text-embedding-3-small")
    return _collection, _embedder


def retrieve(
    query: str,
    k: int = 5,
    source_filter: str | None = None,
) -> list[dict]:
    """
    Semantic search over the regulatory corpus.

    Args:
        query:         Natural-language query.
        k:             Number of passages to return.
        source_filter: If set, restrict to a single PDF filename.

    Returns list of dicts:
        text      str   — passage text
        citation  str   — human-readable source (e.g. "PMLA 2002 (Act No. 15 of 2003)")
        source    str   — PDF filename
        section   str   — section header detected in the chunk
        page      int   — page number where the chunk starts
        score     float — cosine similarity, 0–1 (higher = more relevant)
    """
    collection, embedder = _get_clients()

    query_vec = embedder.embed_query(query)
    where = {"source": source_filter} if source_filter else None

    results = collection.query(
        query_embeddings=[query_vec],
        n_results=k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    passages = []
    for text, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        passages.append(
            {
                "text": text,
                "citation": meta["citation"],
                "source": meta["source"],
                "section": meta["section"],
                "page": meta["page"],
                "score": round(1.0 - dist, 4),
            }
        )

    return passages


def format_passage(p: dict, idx: int) -> str:
    """Pretty-print a single passage for inspection."""
    lines = [
        f"[{idx}] {p['citation']} | {p['section']} | p.{p['page']} | score={p['score']}",
        "-" * 72,
        p["text"][:600] + ("..." if len(p["text"]) > 600 else ""),
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # Sanity-test queries from the Phase 3 spec
    QUERIES = [
        "structuring threshold cash transaction reporting India",
        "STR filing timeline days suspicious transaction",
        "politically exposed person definition enhanced due diligence",
    ]

    print("=== Vigil RAG sanity test ===\n")
    for query in QUERIES:
        print(f"QUERY: {query}")
        print("=" * 72)
        results = retrieve(query, k=5)
        for i, p in enumerate(results[:2], 1):
            print(format_passage(p, i))
        print()
