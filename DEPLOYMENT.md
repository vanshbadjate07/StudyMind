# Deploying StudyMind, entirely on free tiers

The pieces and why each host was chosen:

| Piece | Host | Why |
|---|---|---|
| Backend | Hugging Face Spaces (Docker) | The embedding model needs ~1.5 GB RAM. Render's free tier (512 MB) OOMs on it; HF's free CPU tier gives 16 GB and persistent storage, no card required. |
| Frontend | Vercel | Static Vite output, free, global CDN. |
| Database | Neon Postgres | Free Postgres that survives redeploys. HF's container filesystem is ephemeral, so SQLite there would be wiped on every restart. |
| LLM | Cerebras → Groq → Gemini free tiers | Already built into the backend; the chain fails over between providers and between multiple keys per provider. |
| Speech-to-text | Groq hosted Whisper | Free tier, no model download; used automatically when a Groq key is set. |

Nothing below needs a credit card.

## 1. Database — Neon

1. Create a project at [neon.tech](https://neon.tech) (free tier).
2. Copy the connection string and change the scheme for the async driver:

   ```
   postgresql://USER:PASSWORD@HOST/dbname
   →
   postgresql+asyncpg://USER:PASSWORD@HOST/dbname
   ```

   The `+asyncpg` suffix is required — the backend is async throughout.

No manual schema setup: migrations run automatically on the backend's first
startup.

## 2. Backend — Hugging Face Space

1. Create a new Space at [huggingface.co/new-space](https://huggingface.co/new-space),
   SDK **Docker**, hardware **CPU basic (free)**.
2. Push the `backend/` directory as the Space's content. The simplest way,
   from the repository root:

   ```bash
   git subtree push --prefix backend https://huggingface.co/spaces/YOUR_NAME/studymind-api main
   ```

   The Space builds `backend/Dockerfile` as-is. It already respects HF's
   conventions: it listens on `$PORT`, runs as uid 1000, and bakes the
   embedding model into the image so the Space does not re-download it on
   every cold start.
3. In the Space's **Settings → Variables and secrets**, set:

   | Variable | Value |
   |---|---|
   | `PORT` | `7860` (HF's expected port) |
   | `STUDYMIND_DATABASE_URL` | the Neon URL from step 1 (secret) |
   | `STUDYMIND_CEREBRAS_API_KEYS` | `["key1"]` or `["key1","key2"]` (secret) |
   | `STUDYMIND_GROQ_API_KEYS` | same shape (secret) |
   | `STUDYMIND_GEMINI_API_KEYS` | same shape (secret) |
   | `STUDYMIND_CORS_ORIGINS` | `["https://YOUR-APP.vercel.app"]` |
   | `STUDYMIND_DATA_DIR` | `/data` — only if you enable persistent storage |

   Key sources, all free: [cloud.cerebras.ai](https://cloud.cerebras.ai),
   [console.groq.com](https://console.groq.com),
   [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
   At least one provider must have a key; more providers and more keys per
   provider just add resilience and quota.

4. **Uploads and vectors.** Without persistent storage, uploaded files and
   the Chroma index live on the container filesystem and vanish on restart
   (the metadata in Neon survives, so documents will show as present but
   lose retrieval). For a demo that is usually acceptable; to keep them,
   enable the Space's persistent storage and set `STUDYMIND_DATA_DIR=/data` —
   that single variable relocates uploads, the vector store and generated
   decks onto the mounted disk.

The API is then at `https://YOUR_NAME-studymind-api.hf.space`. Check
`/health` returns `{"status":"ok"}`.

## 3. Frontend — Vercel

1. Import the GitHub repository at [vercel.com/new](https://vercel.com/new).
2. Set **Root Directory** to `frontend`. Vercel detects Vite and uses
   `npm run build` / `dist` automatically.
3. Add one environment variable:

   | Variable | Value |
   |---|---|
   | `VITE_API_BASE_URL` | `https://YOUR_NAME-studymind-api.hf.space` |

   It is baked in at build time (Vite inlines it), so changing it later
   means redeploying — that is expected.
4. Deploy, then make sure the Vercel URL is listed in the backend's
   `STUDYMIND_CORS_ORIGINS` exactly, scheme included.

## 4. Smoke test

1. Open the Vercel URL, create a notebook, upload a small PDF.
2. Wait for **Ready**, confirm the overview generates.
3. Ask a chat question — the answer should cite your document.
4. Generate a quiz and a deck; download the .pptx.
5. Start an interview, give one deliberately bad answer, and confirm the
   next question is marked **Follow up** on the same topic.

## Free-tier limits worth knowing

- **HF Spaces** sleep after ~48 h of inactivity; the first request after
  that waits for a cold start (~1 min). Startup is migration + model load,
  both fast because the model is baked into the image.
- **Neon** autosuspends its compute after inactivity; the first query pays
  a ~1 s resume.
- **Provider quotas** reset daily; the chain moves to the next key/provider
  automatically, so a single exhausted key degrades nothing.
- **Groq Whisper** caps audio uploads at 25 MB; the recorder stops at three
  minutes long before that matters.
