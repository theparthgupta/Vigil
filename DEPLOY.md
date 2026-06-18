# Deploying Vigil

Vigil is a **single FastAPI service** that serves both the JSON API and the web
UI (the old Streamlit app was removed). One deploy → one public URL that hosts
everything. These files are included:

- `Procfile` — `web: uvicorn api.main:app --host 0.0.0.0 --port $PORT` (Railway/Heroku-style)
- `render.yaml` — Render Blueprint (build + start + health check + env vars)
- `runtime.txt` — pins Python 3.12 (chromadb/pyarrow/onnxruntime wheels are reliable there)

> I (the agent) **cannot create the live URL for you** — that requires logging
> into your Render/Railway account. The steps below take ~5 minutes.

---

## 1. Secrets — rotate first

The keys committed earlier to `.env` and pasted in chat are **compromised**.
Before going public, rotate them:
- OpenAI: <https://platform.openai.com/api-keys> — delete the old key, create new.
- LangSmith: <https://smith.langchain.com> → Settings → API Keys — revoke + recreate.

Never commit `.env` (it is gitignored). Set keys in the host's dashboard instead.

Required env vars:

| Var | Value |
|---|---|
| `OPENAI_API_KEY` | your rotated key (secret) |
| `LANGSMITH_API_KEY` | your rotated key (secret) |
| `LANGSMITH_PROJECT` | `vigil` |
| `LANGSMITH_TRACING` | `true` |

---

## 2. The vector store — the one real gotcha

The app needs the Chroma vector store (`rag/chroma_db/`) at runtime. It is
**gitignored**, so it is NOT in the repo.

**This is now automatic.** On startup, `api/main.py` checks whether the Chroma
collection has any chunks; if it is empty (a fresh Render deploy), it runs the
ingest pipeline from the PDFs in `regs/` before the app accepts requests, and
logs `Building RAG corpus from regs/... done (N chunks)`. So you do not need a
persistent disk or a build step — just make sure `OPENAI_API_KEY` is set (used
to embed the chunks) and the regulatory PDFs are present.

Consequences:
- **First boot is slow** (~30–90 s) while the corpus embeds; Render's health
  check tolerates the startup window, but the first deploy takes longer than later
  ones. Subsequent boots on the same instance are instant (collection already populated).
- The four **public** PDFs are committed, so a stock deploy builds a ~900-chunk
  corpus automatically. The FIU-IND document is gitignored (see below); with it
  absent the corpus is slightly smaller but fully functional.
- For a paid instance you can still add a persistent disk mounted at
  `rag/chroma_db/` to skip the rebuild entirely.

### ⚠️ Confidentiality note
`regs/Reporting_Format.pdf` (FIU-IND) carries a **"not for general distribution"**
clause, so it is gitignored and not deployed. The PMLA Act, PMLA Rules, RBI Master
Directions and APG report are public and committed. If you want the FIU document in
the live corpus, upload it to the instance out-of-band; do not commit it to a public repo.

---

## 3. Deploy — Render (Blueprint)

1. Push this repo to GitHub.
2. Render dashboard → **New → Blueprint** → pick the repo. It reads `render.yaml`.
3. Fill the two secret env vars when prompted.
4. Make the vector store available (Option A or B above).
5. Deploy. Your URL: `https://vigil-XXXX.onrender.com` (UI at `/`, API at `/health`, `/sample`, `/investigate`).

### Or Railway
1. New Project → Deploy from GitHub repo.
2. Railway auto-detects the `Procfile`. Add the env vars.
3. Handle the vector store (Railway volumes = Option A, or build-time ingest = Option B).

---

## 4. Free-tier caveats
- **Cold starts:** free instances sleep; first request after idle can take ~30–60 s.
- **Memory:** chromadb + langchain can be heavy near the 512 MB free ceiling. If it
  OOMs, use a small paid instance.
- **Latency:** one `/investigate` call makes 3–4 LLM calls (~15–30 s). Synchronous
  by design; acceptable for a demo.
