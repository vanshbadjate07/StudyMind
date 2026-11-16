# Deploying StudyMind, entirely on free tiers

> **Status note.** This guide was rewritten after Hugging Face put Docker
> Spaces behind its PRO subscription (mid-2026) - verified directly against
> their API. The free path today is a slim backend on Render with
> embeddings served by Google's free embedding API instead of in-process
> torch, which Render's 512MB cannot hold.

| Piece | Host | Why |
|---|---|---|
| Backend | Render free web service | Still card-free. 512MB RAM, which fits the app once embeddings are remote. Sleeps after 15 min idle; first request after pays a ~30-60s cold start. |
| Embeddings | Gemini embedding API | Free tier, same keys as the LLM chain. `STUDYMIND_EMBEDDING_PROVIDER=gemini` switches the whole app; vectors are normalized to match the local model's contract. |
| Frontend | Vercel | Static Vite output, free, global CDN. |
| Database | Neon Postgres | Free Postgres that survives redeploys and does not expire (Render's own free Postgres is deleted after 30 days). |
| LLM / voice | Cerebras → Groq → Gemini free tiers | Already built in, with failover across providers and across multiple keys per provider. |

## 1. Database - Neon

Create a free project at [neon.tech](https://neon.tech), copy the connection
string, and change the scheme to the async driver:

```
postgresql://USER:PASSWORD@HOST/db  →  postgresql+asyncpg://USER:PASSWORD@HOST/db
```

Migrations run automatically on the backend's first startup.

## 2. Backend - Render

1. [dashboard.render.com](https://dashboard.render.com) → New → Web Service →
   connect the GitHub repository.
2. Settings: Root Directory `backend`, Runtime **Python**, Instance **Free**,
   Build command `pip install -r requirements-deploy.txt`, Start command
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
   (`requirements-deploy.txt` is requirements.txt minus sentence-transformers
   and torch - the whole reason the app fits in 512MB.)
3. Environment variables:

   | Variable | Value |
   |---|---|
   | `PYTHON_VERSION` | `3.12.7` |
   | `STUDYMIND_DATABASE_URL` | the Neon URL from step 1 |
   | `STUDYMIND_EMBEDDING_PROVIDER` | `gemini` |
   | `STUDYMIND_GEMINI_API_KEYS` | `["key1"]` (also used for embeddings) |
   | `STUDYMIND_CEREBRAS_API_KEYS` / `STUDYMIND_GROQ_API_KEYS` | `["key1"]` each, optional but recommended |
   | `STUDYMIND_CORS_ORIGINS` | `["https://YOUR-APP.vercel.app"]` |

4. Uploaded files and the Chroma index live on Render's ephemeral disk: they
   vanish on redeploy/restart while the metadata in Neon survives, so
   documents reappear without retrieval until re-uploaded. Acceptable for a
   demo; a paid disk fixes it if it ever matters.

## 3. Frontend - Vercel

Import the repo at [vercel.com/new](https://vercel.com/new), Root Directory
`frontend`, and set `VITE_API_BASE_URL` to the Render URL. It is baked in at
build time, so changing it means redeploying. Afterwards make sure the
Vercel URL appears in the backend's `STUDYMIND_CORS_ORIGINS`, scheme
included.

## 4. Smoke test

Upload a small PDF, wait for Ready, ask a chat question (it should cite the
document), generate a quiz, then start an interview and answer one question
badly - the next question should be marked "Follow up" on the same topic.

## Worth knowing

- **Embedding provider is a one-way switch per store.** Local and Gemini
  vectors are mutually meaningless; switching the provider on an existing
  deployment orphans its stored vectors. Re-upload documents after changing
  it. (This is also why the provider is an explicit setting and never
  inferred from which keys exist.)
- **Retrieval threshold.** `STUDYMIND_CHAT_RELEVANCE_DISTANCE_THRESHOLD`
  (default 1.15) was calibrated against the local model. Gemini vectors may
  warrant re-tuning if grounded chat seems too strict or too lax.
- **Quotas** reset daily; the LLM chain fails over across keys and
  providers automatically.
