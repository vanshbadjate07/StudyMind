# StudyMind

A free, self-hostable AI learning companion. Upload your own study material
into a notebook, get a structured overview of what it contains, then work
with it: ask questions answered strictly from your documents, generate
quizzes and slide decks, and rehearse with a mock interview that scores your
answers against your own material and adapts its questions to how you are
doing.

Built for final-year students preparing for exams and placements, job
seekers preparing interviews from their own notes, and anyone learning a
skill from documents. Everything runs on free tiers or fully offline; no
feature requires a paid service.

## Features

| | |
|---|---|
| **Document upload** | PDF, Word, PowerPoint and plain text. Extracted, chunked, embedded and indexed for retrieval. Every failure mode handled explicitly: corrupted files, password-protected PDFs, empty documents, scanned pages with no text layer. |
| **Structured overview** | Before you ask anything, an automatically generated topic breakdown with key concepts, a short summary, and an estimated study time. |
| **Goal-aware notebooks** | Tell each notebook why you are studying (exam, interview, new skill, exploration, or your own words) and every feature adapts its tone and depth. |
| **Grounded chat** | Questions answered strictly from your material, with page-level citations. If the answer is not in your documents, it says so instead of guessing. An explicit internet-mode toggle, off by default, permits general knowledge. |
| **Quizzes** | Multiple choice, generated from your material. Configurable count, difficulty and focus, with per-question feedback and a running score. |
| **Slides** | A real, downloadable .pptx deck generated from your material, in three styles, with programmatically rendered diagrams. |
| **Mock interview** | The centrepiece. Questions come from your material. Each answer is scored by a trained model, and the next question depends on the last answer: a weak answer gets a simpler follow-up on the same topic, two weak answers flag it and move on. Ends with a report: overall score, weak areas, per-question breakdown with what you missed. |
| **Voice answers** | Speak instead of type. The transcript is shown for correction before scoring, and voice and text share one scoring path. |

## How answers are scored

The interview deliberately does not ask a language model "was this answer
good?". Scores come from a trained gradient-boosting regressor over five
interpretable features: semantic similarity to an ideal answer derived from
your material, key-concept coverage, length ratio, filler-word ratio, and a
non-answer flag.

Three properties fall out of that choice, and they are the reason for it:

- **Consistent** — the same answer scores the same every time.
- **Explainable** — every score decomposes into named numbers the UI shows.
- **Testable** — scoring needs no network call, so it is unit-tested.

Held-out metrics (split grouped by topic, so no topic appears in both train
and test): **MAE 1.37 points on a 0–100 scale, R² 0.992**. Labels are
constructed, not human-graded; `backend/ml/artifacts/metrics.json` states
this plainly, and `backend/ml/train_answer_scorer.py` reproduces the whole
artefact. A deterministic rule-based fallback takes over if the model file
is missing, so the app degrades instead of failing.

## Architecture

```
frontend/   React 19 + TypeScript + Vite + Tailwind v4
backend/    FastAPI (async) + SQLAlchemy
            ├─ SQLite locally / Postgres deployed (one env var, Alembic migrations)
            ├─ Chroma for vectors (metadata never leaks into it, vectors never leak out)
            ├─ sentence-transformers embeddings (all-MiniLM-L6-v2, local)
            └─ scikit-learn answer scorer (committed artefact + training script)
```

**LLM strategy.** One provider chain, chosen by config, identical
application code either way. In production: Cerebras → Groq → Gemini free
tiers, each accepting a *list* of API keys tried in order, so a second free
account roughly doubles a provider's daily quota. Locally and in CI: Ollama,
fully offline. Speech-to-text follows the same pattern: Groq's hosted
Whisper when a key is set, local faster-whisper otherwise.

**Generated artefacts** (overview, quiz, deck) are a row plus a status
(`pending → generating → ready | failed`), produced by a background task
that never raises and never leaves a row stuck, polled by the frontend until
settled. The interview is synchronous instead — a request/response
conversation, because the user is waiting for the interviewer.

## Running locally

Backend (Python 3.12):

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload        # http://localhost:8000, docs at /docs
```

Frontend:

```bash
cd frontend
npm install
npm run dev                          # http://localhost:5173
```

With no LLM keys configured the backend uses a local [Ollama](https://ollama.com)
(`ollama pull qwen2.5:3b`, then `ollama serve`). To use free cloud inference
instead, copy `backend/.env.example` to `backend/.env` and add keys — all
three providers have free tiers with no card required.

Optional, for offline voice transcription without a Groq key:
`pip install -r backend/requirements-voice.txt`.

## Running with Docker

```bash
docker compose up --build
```

Opens the full stack — Postgres, backend, frontend — at
http://localhost:5173 on any OS. First build takes several minutes; the
embedding model is baked into the image so cold starts are predictable.

## Deployment (all free tier)

See [DEPLOYMENT.md](DEPLOYMENT.md) for the complete walkthrough: frontend on
Vercel, a slim backend on Render's free tier with embeddings served by
Google's free embedding API (`STUDYMIND_EMBEDDING_PROVIDER=gemini` - the
512 MB instance cannot hold torch), database on Neon Postgres, inference on
the Cerebras/Groq/Gemini free tiers.

## Tests

```bash
cd backend  && .venv/bin/pytest     # 400+ tests, offline, LLM stubbed
cd frontend && npm run test         # 175 tests
cd frontend && npm run build        # typecheck + production build
```

Parsing is tested against real fixtures — genuinely corrupted, encrypted,
empty and scanned PDFs live in `backend/tests/fixtures/` — not mocks. The
LLM client and the embedder are injected everywhere, so the suite runs
without a network.

## Out of scope, deliberately

- **Accounts and auth** — v1 assumes single-user, local or self-hosted use.
- **Scanned/image-only PDFs** — rejected with a clear message; OCR is not planned.
- **Camera "engagement" analysis** — scoped out. Claims of emotion or honesty
  detection from a webcam would be overclaiming, and the honest version (an
  attentiveness signal) adds little next to answer scoring.
- **YouTube / web ingestion** — deferred, not cancelled.
