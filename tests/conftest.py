"""Shared fixtures: load the train split and bucket by typology."""

import json
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path so `from tools.X import Y` works
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session")
def train_cases() -> list[dict]:
    path = Path(__file__).parent.parent / "data" / "cases_train.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def cases_by_typology(train_cases) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {}
    for case in train_cases:
        key = case["typology"] if case["typology"] else "clean"
        buckets.setdefault(key, []).append(case)
    return buckets
