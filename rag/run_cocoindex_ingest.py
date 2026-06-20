"""
Build (or incrementally update) the Vigil regulatory pgvector index via CocoIndex.

    python rag/run_cocoindex_ingest.py

Runs the declarative flow once: CocoIndex sets up the target table/index and
re-embeds only changed/new PDFs (and prunes orphaned chunks). Prints a per-
document chunk count from the resulting table as a sanity check.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rag.cocoindex_flow import init_cocoindex, vigil_regulatory_corpus
from rag.retrieve_pg import _connect, _TABLE  # reuse the same DB connection helper


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    init_cocoindex()
    print("Setting up target table + indexes...")
    vigil_regulatory_corpus.setup(report_to_stdout=True)
    print("\nUpdating index (incremental)...")
    stats = vigil_regulatory_corpus.update(print_stats=True)
    print(f"\nUpdate stats: {stats}")

    # Per-document chunk counts from the live table
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT source, COUNT(*) FROM {_TABLE} GROUP BY source ORDER BY source")
        rows = cur.fetchall()

    print("\n=== Chunk counts per document ===")
    total = 0
    for source, count in rows:
        print(f"  {source:<32} {count:>5}")
        total += count
    print(f"  {'TOTAL':<32} {total:>5}")


if __name__ == "__main__":
    main()
