"""Interview answer scoring (PRD 6.10).

Scores one interview answer against an ideal answer derived from the user's
own source material. Deliberately *not* "ask the LLM how good this is":

- **Consistency.** The same answer must score the same way twice. An LLM's
  subjective judgement drifts between calls even at temperature 0, which
  makes a score the user can't trust and a feature nobody can regression-test.
- **Explainability.** A score here decomposes into five named, individually
  inspectable numbers, so the UI can say *why* an answer scored 48 rather
  than showing an opaque verdict.
- **Testability.** Scoring runs with no network call and no LLM, so the whole
  decision surface is unit-testable against fixed inputs.

The LLM is still used — to write the question and the ideal answer from the
material — but the judgement of the user's answer is a trained model over
interpretable features.

The embedder is injected (defaulting to the app's own `embed_texts`) so tests
pass a deterministic fake and run without torch or a model download, matching
how the LLM client is injected everywhere else in this codebase.
"""

import json
import logging
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / "ml" / "artifacts"
MODEL_PATH = ARTIFACTS_DIR / "answer_scorer.joblib"
METRICS_PATH = ARTIFACTS_DIR / "metrics.json"

# Order is part of the model's contract: the trained artefact was fitted on
# feature vectors in exactly this order, so changing it silently invalidates
# every saved model. Add new features at the end and retrain.
FEATURE_ORDER = (
    "semantic_similarity",
    "concept_coverage",
    "length_ratio",
    "filler_ratio",
    "non_answer",
)

# Capped rather than unbounded: an answer three times longer than the ideal
# one isn't three times worse than one twice as long, and leaving it
# unbounded let a single rambling answer dominate the feature's range during
# training.
MAX_LENGTH_RATIO = 2.0

FILLER_WORDS = frozenset(
    {
        "um",
        "uh",
        "er",
        "ah",
        "hmm",
        "like",
        "basically",
        "actually",
        "literally",
        "obviously",
        "whatever",
        "stuff",
        "things",
        "yeah",
        "okay",
        "right",
        "well",
        "anyway",
        "somehow",
    }
)

# Multi-word fillers are matched on the normalised text before tokenising,
# since "you know" and "sort of" only read as filler as a phrase — "know"
# and "of" on their own are ordinary words.
FILLER_PHRASES = (
    "you know",
    "sort of",
    "kind of",
    "i mean",
    "i guess",
    "or something",
    "and so on",
    "stuff like that",
)

# Normalised forms that are nothing but a refusal. Compared whole-string, so
# "no idea" is a non-answer while "no idea why it rehashes, but a rising load
# factor triggers it" is a real (if hedged) answer that must still be scored.
_NON_ANSWER_EXACT = frozenset(
    {
        "idk",
        "dunno",
        "no idea",
        "no clue",
        "not sure",
        "not certain",
        "nothing",
        "none",
        "no",
        "skip",
        "pass",
        "na",
        "n a",
        "no answer",
        "no comment",
        "cant say",
        "cannot say",
    }
)

# The "I don't know" family, which has too many surface forms to list.
# Anchored at BOTH ends deliberately: an answer that opens with an admission
# and then answers anyway ("I don't know the term, but it hashes the key to a
# bucket") is a real partial answer worth partial credit. An earlier version
# left the tail unanchored and also made every prefix optional, which both
# swallowed genuine partial answers and matched a bare "know" — the two
# opposite failure modes this shape avoids.
_NON_ANSWER_PATTERN = re.compile(
    r"^(?:i|we)?\s*"
    r"(?:dont|do not|didnt|did not|cant|cannot|wont|will not|have no|dont have any)\s+"
    r"(?:know|knew|remember|recall|understand|get it|idea|clue|a clue|an idea|answer)"
    r"[\s.!?]*$"
)

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9\s]")
_WHITESPACE = re.compile(r"\s+")

# Stopwords are stripped only from key *concepts* before matching, so a
# concept phrased as "the time complexity of lookup" matches an answer that
# says "lookup time complexity" — the connecting words carry no signal about
# whether the user knew the concept.
_CONCEPT_STOPWORDS = frozenset(
    {"a", "an", "the", "of", "in", "on", "to", "for", "and", "or", "is", "are", "be", "its", "it"}
)

Embedder = Callable[[list[str]], list[list[float]]]


@dataclass(frozen=True)
class AnswerFeatures:
    """The five interpretable signals a score decomposes into. Every one is
    independently meaningful to a human reading a score breakdown, which is
    the whole point of this feature set over an opaque embedding."""

    semantic_similarity: float
    concept_coverage: float
    length_ratio: float
    filler_ratio: float
    non_answer: float

    def as_vector(self) -> list[float]:
        return [getattr(self, name) for name in FEATURE_ORDER]

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class AnswerScore:
    score: int
    missed_points: list[str]
    feedback: str
    features: dict[str, float]
    # True when the score came from the rule-based fallback rather than the
    # trained artefact. Surfaced so a deployment missing its model file is
    # visible in logs and tests rather than silently degrading.
    used_fallback: bool


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace. Shared by every
    text feature so they all agree on what a word is."""
    lowered = text.lower().replace("’", "'").replace("'", "")
    stripped = _NON_ALPHANUMERIC.sub(" ", lowered)
    return _WHITESPACE.sub(" ", stripped).strip()


def _tokens(normalized: str) -> list[str]:
    return normalized.split() if normalized else []


def _stem(token: str) -> str:
    """A deliberately crude suffix strip — enough to match "buckets" against
    "bucket" and "hashing" against "hash", without pulling in a real stemmer
    (and its dependency) for a signal this coarse. Short tokens are left
    alone so "is"/"as" aren't mangled into nothing."""
    if len(token) <= 3:
        return token
    for suffix in ("ing", "ies", "es", "ed", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


def is_non_answer(user_answer: str) -> bool:
    """An empty answer, or one that is purely an admission of not knowing.
    Separated out and exported because the interview agent needs this same
    judgement to decide whether to probe a topic further."""
    normalized = _normalize(user_answer)
    if not normalized:
        return True
    if normalized in _NON_ANSWER_EXACT:
        return True
    return _NON_ANSWER_PATTERN.match(normalized) is not None


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Computes the norms rather than assuming unit vectors. The app's real
    `embed_texts` does normalize, but a test's stub embedder has no reason
    to, and silently returning a dot product above 1.0 for un-normalized
    vectors would push the feature outside the range the model was fitted on."""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    # Clamped to [0, 1]: negative cosine means "points the other way", which
    # for answer quality is no different from unrelated, and the model is
    # fitted on a [0, 1] feature.
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def _concept_coverage(answer_tokens: list[str], key_concepts: Sequence[str]) -> tuple[float, list[str]]:
    """Fraction of key concepts the answer touches, plus the ones it missed.
    A concept counts as covered when every content token in it appears
    (stemmed) somewhere in the answer — so a multi-word concept isn't
    credited for a partial match on one common word, but word order and
    connecting words don't matter either."""
    if not key_concepts:
        return 1.0, []

    answer_stems = {_stem(token) for token in answer_tokens}
    missed: list[str] = []
    for concept in key_concepts:
        concept_tokens = [
            _stem(token)
            for token in _tokens(_normalize(concept))
            if token not in _CONCEPT_STOPWORDS
        ]
        if not concept_tokens:
            continue
        if not all(token in answer_stems for token in concept_tokens):
            missed.append(concept)

    considered = sum(
        1
        for concept in key_concepts
        if [t for t in _tokens(_normalize(concept)) if t not in _CONCEPT_STOPWORDS]
    )
    if considered == 0:
        return 1.0, []
    return (considered - len(missed)) / considered, missed


def _filler_ratio(answer_tokens: list[str], normalized_answer: str) -> float:
    if not answer_tokens:
        return 0.0
    single = sum(1 for token in answer_tokens if token in FILLER_WORDS)
    phrase_words = sum(
        normalized_answer.count(phrase) * len(phrase.split()) for phrase in FILLER_PHRASES
    )
    return min(1.0, (single + phrase_words) / len(answer_tokens))


def extract_features(
    user_answer: str,
    ideal_answer: str,
    key_concepts: Sequence[str],
    embedder: Embedder | None = None,
) -> AnswerFeatures:
    """Turns one answer into the five-number feature vector the model scores.
    Pure apart from the embedder call, so it's directly unit-testable."""
    normalized_answer = _normalize(user_answer)
    answer_tokens = _tokens(normalized_answer)
    ideal_tokens = _tokens(_normalize(ideal_answer))

    non_answer = is_non_answer(user_answer)
    coverage, _ = _concept_coverage(answer_tokens, key_concepts)

    if non_answer:
        # Skips the embedding call entirely for an answer with no content to
        # embed — both a correctness point (an empty string's embedding is
        # meaningless, not "0% similar") and the common case on a fast path.
        similarity = 0.0
        coverage = 0.0
    else:
        embed = embedder or _default_embedder()
        vectors = embed([user_answer, ideal_answer])
        similarity = _cosine_similarity(vectors[0], vectors[1]) if len(vectors) == 2 else 0.0

    length_ratio = (
        min(MAX_LENGTH_RATIO, len(answer_tokens) / len(ideal_tokens)) if ideal_tokens else 0.0
    )

    return AnswerFeatures(
        semantic_similarity=round(similarity, 6),
        concept_coverage=round(coverage, 6),
        length_ratio=round(length_ratio, 6),
        filler_ratio=round(_filler_ratio(answer_tokens, normalized_answer), 6),
        non_answer=1.0 if non_answer else 0.0,
    )


def _default_embedder() -> Embedder:
    # Imported lazily so this module can be imported (and most of it tested)
    # without pulling in sentence-transformers and torch.
    from app.services.embeddings import embed_texts

    return embed_texts


# Weights for the fallback path only. Chosen to put most of the score on the
# two features that actually measure understanding (similarity, coverage) and
# only a light penalty on delivery (filler) and a light reward for saying
# enough (length) — then fitted-by-hand to land in the same ballpark as the
# trained model on the tiers in ml/train_answer_scorer.py's corpus, so a
# deployment missing its artefact degrades in accuracy rather than becoming
# nonsense.
_FALLBACK_WEIGHTS = {
    "semantic_similarity": 52.0,
    "concept_coverage": 38.0,
    "length_ratio": 10.0,
    "filler_ratio": -18.0,
}


def _fallback_score(features: AnswerFeatures) -> float:
    """Deterministic weighted score used when the trained artefact is missing
    or unloadable. Exists so the app never hard-fails on a missing model
    file — a self-hostable project can't assume every checkout ran the
    training script, and a scoring feature that 500s is worse than one that's
    slightly less calibrated."""
    if features.non_answer:
        return 0.0
    raw = (
        _FALLBACK_WEIGHTS["semantic_similarity"] * features.semantic_similarity
        + _FALLBACK_WEIGHTS["concept_coverage"] * features.concept_coverage
        + _FALLBACK_WEIGHTS["length_ratio"] * min(1.0, features.length_ratio)
        + _FALLBACK_WEIGHTS["filler_ratio"] * features.filler_ratio
    )
    return max(0.0, min(100.0, raw))


@lru_cache(maxsize=1)
def _load_model() -> Any | None:
    """Loads the trained artefact once per process. Returns None (rather than
    raising) on anything going wrong — a missing file, a joblib/sklearn
    version mismatch, a corrupted artefact — so the fallback takes over and
    the reason is logged instead of surfacing as a request failure."""
    if not MODEL_PATH.exists():
        logger.warning(
            "Answer scoring model not found at %s; using the rule-based fallback. "
            "Run `python -m ml.train_answer_scorer` to build it.",
            MODEL_PATH,
        )
        return None
    try:
        import joblib

        return joblib.load(MODEL_PATH)
    except Exception as exc:  # noqa: BLE001 - any load failure must fall back, not raise
        logger.warning("Could not load the answer scoring model (%s); using the fallback.", exc)
        return None


def load_metrics() -> dict[str, float] | None:
    """The held-out metrics saved alongside the artefact, surfaced so the API
    can report how the model actually performs rather than asking anyone to
    take the score on trust."""
    if not METRICS_PATH.exists():
        return None
    try:
        return json.loads(METRICS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _build_feedback(score: int, features: AnswerFeatures, missed: list[str]) -> str:
    """Plain-language explanation assembled from the same features the score
    came from — so feedback can never contradict the number next to it, which
    is exactly what happens when an LLM writes the prose and a model writes
    the score."""
    if features.non_answer:
        return (
            "No answer was given, so there's nothing to score. Even a partial "
            "attempt scores better than skipping — say what you do recall."
        )

    if score >= 80:
        opening = "Strong answer — it covers the substance of what the material says."
    elif score >= 60:
        opening = "Solid answer, but it leaves out part of what the material covers."
    elif score >= 35:
        opening = "Partially correct. You touched the topic but missed most of the detail."
    else:
        opening = "This doesn't really answer the question as the material frames it."

    parts = [opening]

    if missed:
        shown = ", ".join(missed[:3])
        parts.append(
            f"Not mentioned: {shown}{'…' if len(missed) > 3 else ''}."
        )
    elif score >= 60:
        parts.append("You named every key point the material raises.")

    if features.length_ratio < 0.4 and not features.non_answer:
        parts.append("It's also noticeably shorter than a complete answer — go into more depth.")
    elif features.length_ratio >= MAX_LENGTH_RATIO:
        parts.append("It's much longer than it needs to be; a tighter answer reads better.")

    if features.filler_ratio > 0.12:
        parts.append("Try to cut the filler words — they make a good answer sound less certain.")

    return " ".join(parts)


def score_answer(
    question: str,
    user_answer: str,
    ideal_answer: str,
    key_concepts: Sequence[str],
    embedder: Embedder | None = None,
) -> AnswerScore:
    """Scores one interview answer 0-100 against an ideal answer drawn from
    the user's material.

    `question` is accepted for interface completeness and logging but is
    deliberately not a feature: the question text is identical across every
    answer to it, so it carries no signal about answer quality, and feeding
    it in would only invite the model to learn question-specific quirks from
    a small corpus.
    """
    features = extract_features(user_answer, ideal_answer, key_concepts, embedder)
    _, missed = _concept_coverage(_tokens(_normalize(user_answer)), key_concepts)
    if features.non_answer:
        missed = list(key_concepts)

    model = _load_model()
    used_fallback = model is None
    if model is None:
        raw_score = _fallback_score(features)
    else:
        try:
            raw_score = float(model.predict([features.as_vector()])[0])
        except Exception as exc:  # noqa: BLE001 - a predict failure must fall back, not 500
            logger.warning("Answer scoring prediction failed (%s); using the fallback.", exc)
            raw_score = _fallback_score(features)
            used_fallback = True

    # A regressor is free to predict outside its training range; a score the
    # UI renders as a percentage is not.
    if features.non_answer:
        raw_score = 0.0
    score = int(round(max(0.0, min(100.0, raw_score))))

    return AnswerScore(
        score=score,
        missed_points=missed,
        feedback=_build_feedback(score, features, missed),
        features=features.as_dict(),
        used_fallback=used_fallback,
    )
