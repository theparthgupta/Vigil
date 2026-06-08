# Vigil

> An AI compliance analyst that takes a flagged transaction case, autonomously investigates it using live sanctions data and Indian PMLA/RBI regulations, and produces a legally-grounded STR-format report with a clear recommendation — so a human compliance officer does in 2 minutes what currently takes 40.

---

## Phase Status

| Phase | Name | Status |
|-------|------|--------|
| 0 | Setup | ✅ Done |
| 1 | Synthetic dataset | 🔲 Not started |
| 2 | Tool layer | 🔲 Not started |
| 3 | RAG pipeline | 🔲 Not started |
| 4 | LangGraph orchestration | 🔲 Not started |
| 5 | Evaluation harness | 🔲 Not started |
| 6 | Frontend + backend | 🔲 Not started |
| 7 | Deploy + document | 🔲 Not started |

---

## Why this is different

- **India-specific regulations** — cites exact PMLA sections, RBI circular numbers, and FIU-IND STR format fields (not generic AML advice, not US SAR).
- **Eval-first benchmark** — the labeled dataset and metric harness (precision / recall / F1 / FPR) ship before the final agent; every design decision is justified by numbers.
- **Honest failure-mode documentation** — a dedicated section on what the agent gets wrong and why, so recruiters see engineering judgement, not hype.

---

## How to run

```bash
# 1. Clone and enter the repo
git clone <repo-url>
cd vigil

# 2. Create and activate venv
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy and fill in your keys
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY, OPENSANCTIONS_API_KEY, LANGSMITH_API_KEY

# 5. Run the API
uvicorn api.main:app --reload

# 6. Run the Streamlit UI (separate terminal)
streamlit run app/main.py
```

---

## Architecture

```
data/     → synthetic case generator + labeled cases
tools/    → 4 deterministic tool functions (sanctions, patterns, media, profile)
rag/      → regulatory document ingestion + retrieval (Chroma)
agent/    → LangGraph graph, nodes, shared state
eval/     → evaluation harness + metrics
api/      → FastAPI endpoint (POST /investigate)
app/      → Streamlit reviewer UI
regs/     → source regulatory PDFs (PMLA, RBI, FIU-IND)
```

---

## Regulatory scope

- **Act:** Prevention of Money Laundering Act (PMLA) 2002
- **Regulator:** Financial Intelligence Unit – India (FIU-IND)
- **Report type:** STR (Suspicious Transaction Report) — filed within 7 days of detection
- **CTR threshold:** ₹10 lakh
- **Standards:** RBI KYC/AML Master Directions, FATF South Asia typology reports
