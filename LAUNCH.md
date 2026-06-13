# Launch post (X / Twitter)

> Note: project was renamed **Prahari → Vigil**. This is written for the current brand, Vigil.

## Main tweet (≤280 chars)

```
Built Vigil: an autonomous AML investigation agent for Indian banks.

Flagged txn → sanctions + PMLA/RBI rules (RAG) → ESCALATE/DISMISS + a citation-grounded STR.

40-case locked holdout: precision 1.00, recall 1.00, 0% false positives on clean.

🔗 github.com/<you>/vigil
```
*(271 characters)*

## Thread (optional follow-ups)

**2/**
```
It's a 4-node LangGraph agent: Planner → Investigator → Reasoner → Reporter.
The LLM plans, reasons, and writes. It never does arithmetic — all transaction
features come from deterministic Python, so it can't hallucinate an amount.
```

**3/**
```
Eval-first. Baseline exposed one bug: the planner skipped sanctions screening on
domestic-looking cases (recall 0.78). One prompt change → recall 1.00, with zero
cost to precision. Every change justified by numbers.
```

**4/ (the honest one)**
```
Caveat I won't hide: those perfect scores are on synthetic, cleanly-separable
data. It proves the agent wires its tools together correctly — NOT that it'd hold
up on noisy real bank data. Full "where it still fails" section in the README.
```

**5/**
```
Stack: Python · LangGraph · GPT-4o-mini · ChromaDB (RAG over PMLA 2002, PMLA
Rules, RBI KYC MD, FIU-IND STR format) · FastAPI · LangSmith traces.
```
