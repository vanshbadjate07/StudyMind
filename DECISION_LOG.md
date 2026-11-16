# Decision log

Architectural decisions, why they were made, and what they trade away.
Newest last.

---

**1. Two stores, kept strictly separate.** SQLite/Postgres holds structured
metadata; Chroma holds vectors only. Vector data never leaks into the
relational store and metadata never lives only in Chroma. *Why:* each store
is replaceable independently, and deleting a document is a well-defined
operation (file + rows + vectors). *Trade-off:* deletes must touch both
stores, so deletion code is more careful than a single-store design.

**2. The notebook is the unit of study.** Overview, chat, quiz, deck and
interview all operate on a notebook's combined material, not per-document.
*Why:* people study subjects, not files; a subject is usually several PDFs.
*Trade-off:* one overview per notebook meant a real migration when this
replaced per-document overviews.

**3. Generated artefacts are a row plus a status.** Overview, quiz and deck
each keep one row per notebook (`pending → generating → ready | failed`),
produced by a background task that never raises and always settles the row,
polled by the frontend. *Why:* generation takes tens of seconds; a request
that blocks for that long times out, and a job that can crash without
settling its row leaves the UI spinning forever. *Trade-off:* polling
traffic, and per-feature hooks to manage it.

**4. One LLM client interface, provider chosen by config.** A cloud chain
(Cerebras → Groq → Gemini) where each provider takes a *list* of keys tried
in order, falling back to local Ollama when no key is set. *Why:* local
development and CI run free and offline; the deployed app cannot run Ollama
on a free host, so it routes identical calls to free cloud tiers. Multiple
keys per provider multiply free daily quota without code changes. *Trade-off:*
behaviour differs slightly between a 3B local model and a 120B hosted one,
so prompts carry defensive instructions the big models don't need.

**5. A trained model scores interview answers, not an LLM.** Gradient
boosting over five interpretable features, trained offline, committed with
held-out metrics, with a deterministic rule-based fallback. *Why:*
consistency (same answer, same score), explainability (the score decomposes
into named numbers), and testability (no network in the scoring path). An
LLM's opinion has none of those. *Trade-off:* the training labels are
constructed rather than human-graded, and the metrics file says so; the
model measures content coverage, not eloquence.

**6. The interview is synchronous.** Unlike the generated artefacts, each
turn is a plain request/response. *Why:* there is no artefact being built in
the background — the user is waiting for the interviewer's next question,
and a 202-plus-polling dance would add latency and complexity to a
conversation. *Trade-off:* an LLM hiccup surfaces as a request error, so the
scored answer is committed *before* the next question is generated and a
`/continue` endpoint picks up a stranded interview.

**7. The interview's agenda comes from the overview.** Topics are taken from
the notebook's structured overview when one is ready, with an LLM fallback,
frozen at session start. *Why:* the overview already is the app's statement
of what the material contains; a second, different topic analysis would
contradict it. Freezing prevents the agenda shifting mid-interview when a
document finishes processing. *Trade-off:* an overview that missed a topic
means the interview misses it too — one view of the material, right or wrong.

**8. Probing is capped at two consecutive weak answers per topic.** Then the
topic is flagged as a weak area and the interview moves on. *Why:* without a
cap, a topic the candidate simply doesn't know absorbs every remaining
question — the failure mode that makes an "adaptive" interview worse than a
fixed list. A property test drives the loop with all-weak answers and
asserts termination.

**9. Voice answers are transcribed, reviewed, then scored — not scored
directly from audio.** Transcription is its own endpoint; the transcript
lands in the answer box for correction and goes through the same `/answer`
endpoint as typing. *Why:* one scoring path means text and voice can never
drift apart, and a mis-transcription the user never saw can't cost them a
question and read as the scorer being wrong. *Trade-off:* two round-trips
instead of one, and a deliberate deviation from the original one-shot
`/answer/voice` plan.

**10. faster-whisper is an optional dependency.** `requirements-voice.txt`,
imported lazily, with Groq's hosted Whisper preferred whenever a Groq key
exists. *Why:* it pulls in ~500 MB of weights most installs never use.
*Trade-off:* offline voice requires one extra install step, stated in the
error message itself.

**11. Alembic owns the schema; existing databases are adopted, not rebuilt.**
A pre-Alembic database is stamped at a baseline revision (after the legacy
SQLite patches run and `create_all` fills any missing tables), then upgraded.
*Why:* the same migrations must run on SQLite locally and Postgres deployed,
and the hand-rolled PRAGMA patches were SQLite-only. Stamping is what lets a
database full of real data join the managed path without being touched.
*Trade-off:* the adoption logic itself needs tests — three distinct database
states, each covered.

**12. Backend deploys to a Hugging Face Docker Space.** *Why:* the embedding
model wants ~1.5 GB RAM; Render's free 512 MB OOMs, HF's free tier has
16 GB. Running embeddings locally in-container keeps retrieval identical in
development and production — swapping to an embeddings API would have
changed every stored vector. *Trade-off:* Spaces sleep when idle, so the
first request after a quiet period pays a cold start; the model is baked
into the image to keep that cost predictable.

**13. No accounts in v1.** Single-user, local or self-hosted.
*Why:* auth is a solved problem that adds no learning value here, and the
self-hosted deployment is inherently single-tenant. *Trade-off:* the hosted
demo is one shared workspace; adding auth later means scoping every table by
user, which the notebook-scoped schema already makes straightforward.
