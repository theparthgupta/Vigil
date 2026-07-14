# Deploying Vigil

Vigil is a **single FastAPI service** (API + UI) plus **Postgres with pgvector**
(RAG corpus, case store, audit trail). Both stores self-build on first boot:
CocoIndex embeds the regulatory corpus (needs `OPENAI_API_KEY`; a few minutes,
pennies of embedding spend) and the anomaly model trains from the committed
data. Restarts are fast - everything is idempotent.

## 0. Secrets - rotate first

Any key that has ever been committed or pasted into a chat is compromised.
Before going public, rotate:
- OpenAI: <https://platform.openai.com/api-keys>
- OpenSanctions (optional): <https://www.opensanctions.org/api/>
- LangSmith (optional): <https://smith.langchain.com/>

## 1. Docker Compose (simplest)

```bash
OPENAI_API_KEY=sk-... docker compose up --build
# http://localhost:8000/
```

Works anywhere Docker runs (a VPS, a homelab, a cloud VM). The compose file
provisions pgvector Postgres with a persistent volume alongside the app.

## 2. Render (managed, free tier)

`render.yaml` is a Blueprint that provisions the web service **and** a managed
Postgres database wired in via `DATABASE_URL`:

1. Push the repo to GitHub.
2. Render dashboard → New → Blueprint → select the repo.
3. Set `OPENAI_API_KEY` (and optionally `LANGSMITH_API_KEY`) when prompted.
4. First deploy takes a few minutes while the corpus embeds; `/health` goes
   green when ready.

Notes:
- Render free Postgres instances **expire after 90 days** - fine for a demo,
  use a paid plan for anything persistent.
- Render Postgres supports the `vector` extension; CocoIndex creates it
  automatically on first boot.
- `Procfile` and `runtime.txt` are kept for Railway/Heroku-style platforms;
  on those you must attach a pgvector-capable Postgres yourself and set
  `DATABASE_URL`.

## 3. Anything else

Requirements are just: Python 3.12, `pip install -r requirements.txt`,
a reachable Postgres with the pgvector extension available, and two env vars
(`DATABASE_URL`, `OPENAI_API_KEY`). Start with
`uvicorn api.main:app --host 0.0.0.0 --port 8000`.

Optional tuning knobs (see `.env.example`): `VIGIL_THRESHOLD` (triage gate,
default 0.60), `VIGIL_USD_INR` (cost display conversion, default 84).
