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

The app needs the Chroma vector store (`rag/chroma_db/`, ~29 MB) at runtime. It
is **gitignored**, so it is NOT in the repo. Pick one:

**Option A — Render persistent disk (recommended).**
Add a disk to the service (mount at `/opt/render/project/src/rag/chroma_db`),
then upload your locally-built `rag/chroma_db/` once. The free plan does not
include disks, so this needs a paid instance.

**Option B — Re-ingest at build time.**
Place the regulatory PDFs in `regs/` on the build (they are also gitignored),
add `python rag/ingest.py` to the `buildCommand`, and ensure `OPENAI_API_KEY`
is available at build (embeds 928 chunks, a few cents). Cleanest for a public
repo because no regulatory text is committed.

**Option C — Commit the store.** Remove `rag/chroma_db/` from `.gitignore` and
commit it. Simplest, but see the confidentiality note below.

### ⚠️ Confidentiality note (read before Option C)
`regs/Reporting_Format.pdf` (FIU-IND) carries a **"not for general distribution"**
clause. Its text is also embedded inside the Chroma store. **Do not commit that
document — or a vector store containing it — to a public repo** without
clearance. The PMLA Act, PMLA Rules, RBI Master Directions and APG report are
public; the FIU reporting-format spec is the sensitive one. If you go public,
prefer Option A/B, or rebuild the store excluding the FIU document.

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
