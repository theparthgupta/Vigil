# ROADMAP.md — Vigil - AML Compliance Agent

**One-sentence pitch:** An AI compliance analyst that takes a flagged transaction case,
autonomously investigates it using live sanctions data and Indian PMLA/RBI regulations,
and produces a legally-grounded STR-format report with a clear recommendation — so a
human compliance officer does in 2 minutes what currently takes 40.

## Guiding principles (read before every phase)
1. **Eval-first.** The labeled dataset and the metric harness come BEFORE the final agent.
   Every design decision is justified by whether it moves precision / recall / F1 / FPR.
2. **India-specific or it's worthless.** Cite exact PMLA sections, RBI circular numbers,
   FIU-IND **STR** format (NOT US "SAR"). CTR threshold = ₹10 lakh. STR filed
   **promptly** (statutory, PMLA Rules 2005 Rule 8(2)); 7 working days = industry norm, NOT statute.
3. **One phase per Claude Code session.** Use plan mode to design, `/clear` between phases,
   subagents for research, and log every real decision to DECISIONS.md.
4. **Build the boring, deterministic parts as plain Python first.** The LLM orchestrates;
   it should not be doing arithmetic the code can do exactly.

---

## Phase 0 — Setup (Day 0, ~1-2 hrs)
- [ ] `git init`. Add CLAUDE.md, .claude/skills/explain-change/, DECISIONS.md, this ROADMAP.md.
- [ ] Python venv (3.11+). Create `requirements.txt` (langgraph, langchain, langchain-openai
      or anthropic, chromadb, fastapi, uvicorn, streamlit, pydantic, pandas, scikit-learn,
      python-dotenv, langsmith).
- [ ] `.env` for keys (LLM provider, OpenSanctions trial key, LangSmith). Add `.env` to .gitignore.
- [ ] Create LangSmith account + project; set tracing env vars so EVERY run is traced from day one.
- [ ] Decide repo layout, e.g.:
      `data/` (generator + cases) · `tools/` (4 tool fns) · `rag/` (ingest + retrieve) ·
      `agent/` (graph, nodes, state) · `eval/` (harness + metrics) · `api/` (FastAPI) ·
      `app/` (Streamlit) · `regs/` (source PDFs).
- [ ] Fill in the Commands section of CLAUDE.md.

## Phase 1 — Synthetic dataset (Week 1) ← the foundation
This is what makes everything else evaluable. Do it first.
- [ ] Define the case schema (pydantic): customer profile, transaction history, ground-truth
      label (suspicious | clean), and for suspicious cases a `typology` field.
- [ ] Write a generator that produces ~200 cases:
      - **Structuring**: multiple deposits clustered just below ₹10 lakh within a month.
      - **Sanctions hit**: a counterparty name that matches the OpenSanctions list.
      - **Rapid pass-through**: large credit immediately followed by many debits to new payees.
      - **Clean**: realistic SMB + retail profiles with plausible-but-benign activity.
- [ ] Make it reproducible (fixed random seed) and balanced enough to measure FPR meaningfully.
- [ ] Hold out a small set you NEVER tune on, to check for overfitting to your own prompts.
- [ ] Eyeball 10 cases manually — do the labels actually make sense? Garbage labels = garbage eval.

## Phase 2 — Tool layer (Week 1-2)
Each tool is a pure Python function returning structured JSON. Test in isolation first.
- [ ] **Tool 1 — Sanctions/PEP lookup.** Call OpenSanctions `/match` (30-day trial key) OR
      self-host yente against the free non-commercial bulk data. Return match score + entity +
      sanctions program + risk tags. Handle "no match" cleanly.
- [ ] **Tool 2 — Transaction pattern analyzer (deterministic).** Compute features in code:
      avg/median size, velocity over 7/30/90 days, counterparty diversity, and a structuring
      indicator (count of transactions in the ₹9–10 lakh band within a window). No LLM here.
- [ ] **Tool 3 — Adverse media.** Stub with a web-search call returning title/snippet/url.
      Keep the interface stable so you can swap in a real provider later.
- [ ] **Tool 4 — Customer profile summarizer.** Reads stated business type, history, prior flags;
      returns a compact risk-relevant summary.
- [ ] Write a quick unit test per tool against a couple of Phase-1 cases.

## Phase 3 — RAG pipeline (Week 2)
- [ ] Collect source texts into `regs/`: PMLA 2002, RBI KYC/AML Master Directions, FIU-IND STR
      filing guidelines, 2-3 FATF South Asia typology reports.
- [ ] Chunk (respect section boundaries — legal text hates naive fixed-size splits), embed,
      store in Chroma with metadata (source, section/circular number).
- [ ] Write `retrieve(query) -> passages[]` that returns text + citation metadata.
- [ ] Sanity-test retrieval: query "structuring threshold" / "STR timeline" and confirm the
      right passages come back with citable references. Bad retrieval poisons the Reasoner.

## Phase 4 — LangGraph orchestration (Week 2-3) ← the core skill you're demonstrating
Use plan mode in Claude Code to design the state + graph before writing it.
- [ ] Define the shared **State** (typed): case, collected evidence, retrieved passages,
      decision, draft report.
- [ ] **Planner node** — given the case, decides which tools to run.
- [ ] **Investigator node** — executes the chosen tools, writes evidence into state.
- [ ] **Reasoner node** — synthesizes evidence against retrieved regulation, decides
      escalate | dismiss, with explicit reasons + citations.
- [ ] **Reporter node** — emits a structured **STR-format** report (not SAR), citing chapter/verse.
- [ ] Wire edges (Planner → Investigator → Reasoner → Reporter); add a conditional loop back to
      Investigator if the Reasoner needs more evidence.
- [ ] Get ONE case flowing end-to-end and inspect the full trace in LangSmith.

## Phase 5 — Evaluation harness (Week 3) ← the section recruiters stop scrolling for
- [ ] Run all ~200 cases through the agent; capture escalate/dismiss + the report.
- [ ] Compute precision, recall, F1, and **false-positive rate on clean cases** specifically.
- [ ] Record this as the **baseline**. Tag the run in LangSmith.
- [ ] Iterate deliberately: change ONE thing (prompt / tool / retrieval), re-run, compare.
      Every change must be justified by the numbers. Log each experiment to DECISIONS.md.
- [ ] Save the learning curve (baseline vs optimized) for the README.

## Phase 6 — Frontend + backend (Week 4)
- [ ] FastAPI: single `POST /investigate` endpoint that takes a case, returns decision +
      reasoning chain + report. (No real banking data, no secrets in URLs.)
- [ ] Streamlit: reviewer sees the case, the agent's full reasoning chain + citations, and can
      **approve / override**. The human-in-the-loop framing is part of the pitch.

## Phase 7 — Deploy + document (Week 4)
- [ ] Deploy to Render with a public URL.
- [ ] README: the one-sentence pitch as the headline, architecture diagram, the baseline-vs-
      optimized learning curve, and how to run it.
- [ ] Write the **"Where it still fails"** section — the case types it gets wrong and why.
      This makes the project look more serious, not less.

---

## What separates this from every other GitHub "AML agent"
1. India regulatory specificity (exact PMLA sections, RBI circulars, FIU-IND STR format).
2. Eval-first: the benchmark ships before the final agent; decisions are metric-driven.
3. Honest failure-mode documentation.

## Things to get right (accuracy notes)
- It's **STR** (Suspicious Transaction Report) in India, not SAR. CTR threshold ₹10 lakh.
  STR filing deadline is **"promptly"** — statutory, PMLA (Maintenance of Records) Rules
  2005, Rule 8(2) (as amended 2015). The often-quoted "7 working days" is an **industry
  norm / internal SLA, NOT the statutory deadline** — the original 7-day Rule 8(2) was
  replaced by "promptly" in 2015. CTR is monthly, by the 15th of the succeeding month
  (Rule 8(1)). The Reasoner must cite Rule 8(2) verbatim and state this distinction.
- OpenSanctions is free for **non-commercial** use only; use the 30-day trial key or self-host
  yente. Don't imply a free commercial API in the README.
- Keep arithmetic/feature computation in deterministic Python, not in the LLM.
