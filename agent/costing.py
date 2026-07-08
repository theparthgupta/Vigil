"""
Deterministic LLM cost tracking for Vigil investigations (Phase 11).

A LangChain callback counts the exact tokens every LLM call in a graph run
consumes; the ₹ cost is then computed in plain Python from published prices.
The LLM never does the arithmetic.

Scope note: this counts chat-model tokens (gpt-4o-mini). Embedding calls for
RAG retrieval are NOT captured by chat callbacks — at $0.02/1M tokens they are
~1% of a run's cost, documented here rather than silently ignored.
"""

from __future__ import annotations

import os

from langchain_core.callbacks import BaseCallbackHandler

# gpt-4o-mini published pricing (USD per 1M tokens).
_USD_PER_1M_INPUT = 0.15
_USD_PER_1M_OUTPUT = 0.60

# Fixed conversion for display; override with VIGIL_USD_INR.
USD_INR = float(os.getenv("VIGIL_USD_INR", "84.0"))


class TokenUsageHandler(BaseCallbackHandler):
    """Accumulates token usage across every LLM call in one graph run."""

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.llm_calls = 0

    def on_llm_end(self, response, **kwargs) -> None:
        counted = False
        for gens in response.generations:
            for g in gens:
                usage = getattr(getattr(g, "message", None), "usage_metadata", None)
                if usage:
                    self.input_tokens += usage.get("input_tokens", 0)
                    self.output_tokens += usage.get("output_tokens", 0)
                    counted = True
        if not counted:
            # Older providers report usage on llm_output instead.
            usage = (response.llm_output or {}).get("token_usage", {})
            self.input_tokens += usage.get("prompt_tokens", 0)
            self.output_tokens += usage.get("completion_tokens", 0)
        self.llm_calls += 1

    def summary(self) -> dict:
        """Tokens + cost, computed deterministically from the price table."""
        cost_usd = (
            self.input_tokens / 1e6 * _USD_PER_1M_INPUT
            + self.output_tokens / 1e6 * _USD_PER_1M_OUTPUT
        )
        return {
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "cost_usd": round(cost_usd, 6),
            "cost_inr": round(cost_usd * USD_INR, 4),
        }
