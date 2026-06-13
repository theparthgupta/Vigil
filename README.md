# Vigil

> An AI compliance analyst that takes a flagged transaction case, autonomously investigates it against live sanctions data and Indian PMLA/RBI regulations, and produces a legally-grounded **STR-format report** with a clear ESCALATE/DISMISS recommendation — turning a 40-minute manual review into a 2-minute one.

**Stack:** Python · LangGraph · OpenAI GPT-4o-mini · ChromaDB (RAG) · FastAPI · vanilla JS UI · LangSmith
**Live demo:** _deploy in progress — see [DEPLOY.md](DEPLOY.md)_ · **Traces:** LangSmith project `vigil`

---

## The problem

AML (anti-money-laundering) compliance teams drown in alerts. Industry estimates put
**false-positive rates on automated AML alerts above 90–95%** — analysts spend most of
their day clearing noise, and India's FIU-IND receives **millions of STRs a year**. The
bottleneck isn't detection, it's *triage*: reading the case, checking sanctions lists,
recalling the right PMLA section, and writing a defensible report. Vigil automates that
investigation while keeping a human in the loop on the final call.

---

## Architecture

```
                                  ┌─────────────────────────────────────────┐
   flagged case (JSON)            │            LangGraph agent               │
        │                         │                                          │
        ▼                         │   ┌─────────┐    ┌──────────────┐        │
  ┌───────────┐   POST /investigate │ │ PLANNER │──▶ │ INVESTIGATOR │        │
  │  Web UI   │ ───────────────────▶│ │  (LLM)  │    │ (4 det. tools)│       │
  │ (vanilla  │                    │  └─────────┘    └──────┬───────┘        │
  │  JS SPA)  │ ◀───────────────── │                        ▼                │
  └───────────┘   decision +       │                 ┌──────────────┐        │
                  STR + audit      │   ┌──────────┐  │   REASONER   │        │
        ▲                          │   │ REPORTER │◀─│  (LLM + RAG) │        │
        │                          │   │  (LLM)   │  └──────┬───────┘        │
   FastAPI (serves API + UI)       │   └──────────┘         │ conf < 0.6     │
                                   │         ▲              └──▶ loop once ──┐│
                                   │         └─────────────────────────────┘│
                                   └─────────────────────────────────────────┘
                                          │                    │
                                  ┌───────▼────────┐   ┌────────▼─────────┐
                                  │ Chroma RAG     │   │ Deterministic    │
                                  │ 5 regulatory   │   │ tools: sanctions,│
                                  │ docs, 928 chunks│  │ patterns, media, │
                                  │ (PMLA/RBI/FIU) │   │ profile          │
                                  └────────────────┘   └──────────────────┘
```

---

## Results

Vigil is **eval-first**: a labelled synthetic benchmark and a metric harness were built
*before* the final agent, so every change is justified by numbers, not vibes.

### Train learning curve (160 cases) — one deliberate, measured change

The baseline exposed a single failure: the LLM planner was skipping sanctions screening on
domestic-looking cases. **One prompt change** (making sanctions screening mandatory) fixed it:

| Metric | Baseline | Optimized | Δ |
|---|---|---|---|
| Precision | 1.000 | 1.000 | — |
| **Recall** | 0.783 | **1.000** | **+0.217** |
| **F1** | 0.879 | **1.000** | **+0.121** |
| Accuracy | 0.838 | 1.000 | +0.162 |
| FPR on clean (critical) | 0.000 | 0.000 | — |
| `sanctions_hit` detection | 0.350 | **1.000** | **+0.650** |

### Holdout (40 cases) — the honest final score

The holdout set was **locked from the first commit** and never used for tuning.

| Metric | Holdout |
|---|---|
| Precision | **1.000** |
| Recall | **1.000** |
| F1 | **1.000** |
| Accuracy | **1.000** |
| FPR on clean | **0.000** |

Confusion matrix: 30/30 suspicious → ESCALATE, 10/10 clean → DISMISS. Per-typology detection
100% across structuring, sanctions_hit, and rapid_passthrough.

> **Read this honestly.** Perfect holdout scores mean the agent *wires its tools together
> correctly* — not that it would perform this well on real, noisy bank data. The benchmark is
> synthetic and cleanly separable by design. See **[Where it still fails](#where-it-still-fails)**.

---

## How it works

The agent is a 4-node LangGraph state machine. The **LLM plans, reasons, and writes; it never
does arithmetic** — all numeric features come from deterministic Python tools, so the model
can't hallucinate a transaction amount or count.

1. **Planner** *(LLM)* — reads a case summary and chooses which tools to run. Sanctions,
   patterns, and profile screening are mandatory; adverse-media is optional.
2. **Investigator** *(deterministic)* — runs the chosen tools: sanctions/PEP screening,
   transaction-pattern analysis (structuring, rapid pass-through, velocity), adverse-media
   search, and a customer risk profile. Writes structured evidence into state.
3. **Reasoner** *(LLM + RAG)* — retrieves the relevant regulatory passages from Chroma and
   decides **ESCALATE / DISMISS** with a confidence score, grounded in citations. If confidence
   < 0.6, the graph loops back once for a wider evidence pass.
4. **Reporter** *(LLM)* — drafts a structured **FIU-IND STR** with citations down to the
   section/rule and page.

---

## Why this is different

- **India-specific regulatory grounding.** Cites exact PMLA 2002 sections, PMLA Rules 2005
  rules, RBI KYC Master Direction paragraphs, and the FIU-IND STR format — not generic AML
  boilerplate. It correctly distinguishes the **statutory STR deadline ("promptly", Rule 8(2))**
  from the commonly-quoted-but-wrong "7 working days" industry norm.
- **Eval-first benchmark.** The labelled dataset and the precision/recall/F1/FPR harness ship
  *before* the final agent. The baseline→optimized→holdout story is metric-driven and reproducible.
- **Honest failure documentation.** The limits below are stated up front, not buried.

---

## Regulatory corpus (RAG)

928 section-aware chunks across 5 documents, embedded with `text-embedding-3-small` in ChromaDB.
Chunking respects legal section boundaries so citations stay intact.

| Document | Citation | Role |
|---|---|---|
| Prevention of Money-Laundering Act, 2002 | Act No. 15 of 2003 | Core AML statute |
| PMLA (Maintenance of Records) Rules, 2005 | G.S.R. 444(E) | STR/CTR filing deadlines |
| RBI KYC Master Directions, 2025 | DOR.AML.REC.No.88/14.01.002/2025-26 | KYC/EDD, PEP rules |
| FIU-IND Reporting Format v1.14 | FINnet 2.0 | STR structure *(distribution-restricted — not in repo)* |
| APG Yearly Typologies Report, 2024 | Asia/Pacific Group | ML/TF typologies |

---

## How to run locally

```bash
git clone <repo-url> && cd vigil
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                # then add OPENAI_API_KEY (+ optional LANGSMITH_API_KEY)

# build the regulatory vector store (needs the PDFs in regs/ and OPENAI_API_KEY)
python rag/ingest.py

# run the app — API + UI on one server
uvicorn api.main:app --reload       # open http://localhost:8000/
```

Reproduce the evals:

```bash
python eval/run_eval.py --tag baseline  --out eval/results_baseline.json
python eval/run_eval.py --tag optimized --out eval/results_optimized.json
python eval/run_eval.py --tag holdout --cases data/cases_holdout.json --out eval/results_holdout.json
python eval/metrics.py eval/results_holdout.json
pytest -q                            # 63 tests
```

---

## Where it still fails

This section exists on purpose — it's the most important part for anyone evaluating the work.

1. **Perfect synthetic scores ≠ real-world proof.** The benchmark is generated by a script that
   plants clean, separable typology signals that the deterministic tools are built to detect.
   The holdout is held out from *tuning*, not from the *data distribution*. Real bank data is
   noisy — transliterated names, partial records, mixed typologies, adversaries who adapt. Vigil
   has not been tested on any of that and would certainly score lower.
2. **Mandatory tools are prompt-enforced, not code-enforced.** The fix that took sanctions recall
   from 0.35 → 1.00 is a *prompt instruction* telling the LLM planner to always screen sanctions.
   An LLM can disobey a prompt; a production system should hard-code the baseline tool set in the
   investigator node so the guarantee doesn't depend on model compliance.
3. **Retrieval precision is imperfect.** RAG sometimes ranks off-target passages (e.g. an APG
   case study) above the operative rule. The reasoner currently filters this, but on harder/real
   regulation a wrong citation is a serious error. Retrieval needs reranking and evaluation in its
   own right.
4. **Sanctions screening is a fuzzy local fallback.** Without an OpenSanctions API key, name
   matching is `difflib`-based — it will miss transliteration variants and alias structures that a
   real screening engine catches.
5. **The low-confidence loop is untested in practice.** No case in 200 dropped below the 0.6
   confidence threshold, so the conditional re-investigation path has never actually fired on data.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Orchestration | **LangGraph** | Explicit state-machine agent with a conditional loop |
| LLM | **OpenAI GPT-4o-mini** (temp 0) | Cheap, fast, deterministic enough for eval |
| RAG | **ChromaDB** + `text-embedding-3-small` | Local, transparent, section-aware chunks |
| Tools | **Deterministic Python** | All arithmetic out of the LLM (no hallucinated numbers) |
| Backend | **FastAPI** + Uvicorn | Serves the API *and* the UI from one process |
| Frontend | **Vanilla HTML/CSS/JS** | No build step; full control of the dark/light UI + animations |
| Observability | **LangSmith** | Every run traced and tagged (baseline / optimized / holdout) |
| Data | **Pydantic** | Schema for synthetic cases + API request validation |

---

## Project layout

```
data/   synthetic case generator + labelled cases (train + locked holdout)
tools/  4 deterministic investigative tools
rag/    regulatory ingest + retrieval (Chroma)
agent/  LangGraph graph, nodes, state, prompts
eval/   evaluation harness + metrics + results
api/    FastAPI app (serves the agent API + the UI)
app/    static single-page UI (HTML/CSS/JS)
regs/   source regulatory PDFs (gitignored)
```

See **[DECISIONS.md](DECISIONS.md)** for the full engineering narrative — every significant
decision, why it was made, the tradeoffs, and how it was verified.

---

*Synthetic data only. Not legal advice. Built as a portfolio demonstration of agentic AI for
regtech, not a production compliance system.*
