# Debugging report

Real bugs hit while building StudyMind: how each showed up, how it was
diagnosed, what the fix was, and what guards it now. All of these are
reconstructable from the git history; several of the fixes carry the war
story as a code comment at the site of the fix.

---

## 1. Every timestamp was "5 hours ago"

**Symptom.** A notebook created seconds ago showed "Updated 5 hours ago".

**Diagnosis.** SQLite has no timezone-aware storage, so SQLAlchemy returns
naive datetimes. They are UTC in fact, but serialize without an offset
marker — and the browser parses a marker-less ISO string as *local* time,
shifting everything by the viewer's UTC offset. Five hours thirty minutes:
exactly IST.

**Fix.** A shared Pydantic serializer stamps UTC onto every outgoing
timestamp (`TimestampedModel` in `backend/app/schemas.py`), so the API only
ever emits unambiguous `...Z` strings.

**Guard.** Tests assert API timestamps end in `Z`; the model's docstring
tells the story so nobody "simplifies" it away.

## 2. Chat answered confidently from an empty notebook

**Symptom.** A brand-new notebook, zero documents, internet mode off — and
"what is MongoDB?" got a fluent, confident answer. The whole point of the
grounding toggle, defeated.

**Diagnosis.** The prompt told the model not to use its own knowledge.
The small local model ignored the instruction. Prompt-only guarantees are
not guarantees.

**Fix.** With zero ready documents and internet mode off, the LLM is not
called at all — a fixed, honest message instead. The one state where
trusting the model's restraint isn't good enough is handled by never asking
for its restraint.

**Guard.** An API test pins the LLM-is-not-called behaviour for that state.

## 3. A quiz offered the same answer twice — one right, one wrong

**Symptom.** Options included both "Llama" and "LLaMA"; picking the wrong
spelling was marked incorrect.

**Diagnosis.** The generator was told to produce four distinct options; the
model complied typographically, not semantically.

**Fix.** Options are normalized (case, punctuation, whitespace) and any
question with colliding options is dropped — one bad question costs one
question, not the batch.

**Guard.** Unit tests on the normalizer and the filter.

## 4. Scrolling died in the page margins

**Symptom.** Wheel/trackpad scrolling worked over the content column but
silently stopped in the side margins.

**Diagnosis.** The scrollable element and the centered column were the same
node, so the scroll container was only as wide as the column; the margins
belonged to a non-scrolling ancestor.

**Fix.** The scroll container spans the full pane; centering moved to an
inner wrapper. A comment in `App.tsx` marks the spot.

## 5. Retrieval cited material from the wrong subtopic

**Symptom.** A question about Python loops, asked against combinatorial
testing material, got an answer "grounded" in excerpts that didn't address
it — with citations.

**Diagnosis.** The vector-distance threshold had been calibrated against
wildly different topics (biology vs. basketball, >1.7 apart). Same-domain,
different-subtopic pairs land around 1.27–1.37 and slipped under the 1.3
bar. The calibration data was too easy.

**Fix.** Re-measured against realistic pairs: on-topic lands ≤1.10,
same-domain-unrelated ≥1.27. Threshold set to 1.15, with margin on both
sides of the *real* gap. Additionally, if the model's own answer opens by
rejecting the excerpts ("these don't cover…"), the citations and grounded
flag are stripped — the distance signal is not trusted over the model's own
reading.

**Guard.** The measured bands live in a comment on the setting; tests cover
the refusal-detection path.

## 6. Deleting a notebook left interview rows behind

**Symptom.** A new cascade-deletion test failed: interview sessions survived
their notebook's deletion.

**Diagnosis.** The foreign keys declare `ondelete="CASCADE"`, but SQLite
ships with the `foreign_keys` pragma off, so the declaration is inert. The
delete endpoint had always compensated by deleting each dependent table
explicitly — and the two new interview tables weren't on that list.

**Fix.** Added them, children before parents, with a comment explaining why
the explicit deletes exist at all.

**Lesson.** The ORM happily records intentions the database never enforces.
The test was written against behaviour, not the schema, which is the only
reason this surfaced.

## 7. "Latest interview" returned the wrong session

**Symptom.** Start an interview, end it, start another — a test asserting
the second is "latest" got the first.

**Diagnosis.** `created_at` used the database's `CURRENT_TIMESTAMP`, which
in SQLite has one-second resolution. Two sessions in the same second tied
the sort, and the tiebreak fell to a random UUID. The codebase had already
hit this exact class of bug once (chat message ordering) and documented it.

**Fix.** Python-side default with microsecond precision, same as the chat
fix.

**Lesson.** The second instance of a bug class means the first fix's comment
wasn't enough; the new comment points at both sites.

## 8. The non-answer detector called "know" a non-answer and "no idea" an answer

**Symptom.** Four scoring tests failed: "no idea" and "not sure" weren't
detected as giving up, while the single word "know" was.

**Diagnosis.** One regex tried to cover the whole "I don't know" family with
every prefix optional — so the bare keyword matched, while surface forms
not in the alternation fell through.

**Fix.** Split the concept: a small exact-match set for fixed refusals
("no idea", "skip", "idk"…), plus an anchored pattern for the "I don't
know" family that *requires* the negation. Anchoring at both ends keeps
"I don't know the term, but it hashes the key…" scoreable — an answer that
opens with an admission and then answers is a partial answer, not a skip.

## 9. An "obviously safe" guard broke crash recovery

**Symptom.** While moving to Alembic, a pre-existing test failed: the
overview migration no longer recovered from a crash between "rename the old
table aside" and "create the new one".

**Diagnosis.** A new early-return ("table doesn't exist — nothing to do")
also fired in exactly that crash window, where the table's *absence* is the
state the migration exists to repair.

**Fix.** The guard returns early only when neither the table nor its
renamed-aside predecessor exists.

**Lesson.** The crash-window test earned its keep years after being written.
Idempotent migration steps need their recovery paths tested, not assumed.

## 10. The interview report appeared where nobody was looking

**Symptom.** In live testing — not in any unit test — finishing an interview
looked like the answer box just vanished. The report rendered above the
transcript; the user was scrolled to the bottom.

**Fix.** The report scrolls itself into view once per completed session.

**Lesson.** The suite verified the report's *content* perfectly and said
nothing about whether a human would see it. Some bugs only exist at runtime,
which is why every feature here ends with a real click-through.

## 11. The development machine itself was the bug

**Symptom.** The full test suite hung for 20+ minutes at 0% CPU without
collecting a single test. A bare `import fastapi` took 17.7 seconds.

**Diagnosis.** A faulthandler stack dump showed the hang inside
`importlib`'s file reads. The project lived under `~/Documents` with iCloud
Drive's "Desktop & Documents" sync on: the OS had evicted tens of thousands
of files (31,381 of the virtualenv's 43,177, confirmed via the
`SF_DATALESS` flag) and every read blocked on a ~5 KB/s re-download.

**Fix.** Force-materialized the project, moved the 1.6 GB of rebuildable
dependency directories (`.venv`, `node_modules`) outside the synced tree
with symlinks in place, and rebuilt them.

**Lesson.** When the profiler says the code is idle and the wall clock says
otherwise, suspect the filesystem. Also: keep dependency trees out of
cloud-synced folders.
