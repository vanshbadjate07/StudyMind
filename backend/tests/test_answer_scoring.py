"""Tests for interview answer scoring (PRD 6.10).

Every test here runs with a deterministic stub embedder, so the whole suite
stays offline and torch-free — the point of injecting the embedder in the
first place. The real `embed_texts` is exercised by the training script, not
by the unit suite.
"""

import math

import pytest

from app.services import answer_scoring
from app.services.answer_scoring import (
    FEATURE_ORDER,
    AnswerFeatures,
    extract_features,
    is_non_answer,
    score_answer,
)

IDEAL = (
    "A hash table applies a hash function to the key to compute a bucket index. "
    "Collisions are resolved by chaining. Performance degrades when the load factor rises."
)
CONCEPTS = ["hash function", "bucket index", "collisions", "load factor"]


def bag_of_words_embedder(texts: list[str]) -> list[list[float]]:
    """A deterministic stand-in for the real sentence-transformers embedder:
    a bag-of-words vector over the union vocabulary of the texts it's given.
    Not semantically clever, but it makes cosine similarity behave in the
    direction that matters — overlapping wording scores higher than
    disjoint wording — with no model download and no randomness, so these
    assertions are stable."""
    tokenized = [text.lower().split() for text in texts]
    vocabulary = sorted({token for tokens in tokenized for token in tokens})
    if not vocabulary:
        return [[0.0] for _ in texts]
    return [[float(tokens.count(term)) for term in vocabulary] for tokens in tokenized]


def zero_embedder(texts: list[str]) -> list[list[float]]:
    """Degenerate embedder returning zero vectors — exercises the
    divide-by-zero guard in the cosine similarity."""
    return [[0.0, 0.0, 0.0] for _ in texts]


@pytest.fixture(autouse=True)
def _clear_model_cache():
    """_load_model is lru_cached per process, so a test that patches the
    artefact path or forces the fallback would otherwise leak its cached
    result into every later test."""
    _safe_cache_clear()
    yield
    _safe_cache_clear()


def _safe_cache_clear() -> None:
    # Tests that replace _load_model outright (to simulate a broken or
    # out-of-range model) leave a plain function in its place, with no
    # lru_cache and therefore no cache_clear to call.
    clear = getattr(answer_scoring._load_model, "cache_clear", None)
    if clear is not None:
        clear()


@pytest.fixture
def force_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pins scoring to the rule-based path, so tests asserting on score
    *ordering* don't depend on whether a trained artefact happens to be
    present in the checkout. Tests that specifically care about the trained
    model don't use this."""
    monkeypatch.setattr(answer_scoring, "MODEL_PATH", answer_scoring.MODEL_PATH.with_name("missing.joblib"))
    answer_scoring._load_model.cache_clear()


# --------------------------------------------------------------------------
# Non-answer detection
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "\n\t",
        "I don't know",
        "i dont know",
        "I don't know.",
        "no idea",
        "No idea!",
        "I don't remember",
        "I can't remember",
        "not sure",
        "skip",
        "pass",
        "nothing",
    ],
)
def test_non_answers_are_detected(text: str) -> None:
    assert is_non_answer(text) is True


@pytest.mark.parametrize(
    "text",
    [
        # The critical case: an answer that *starts* with an admission but
        # then answers anyway is a real, partially-credited answer. An
        # un-anchored substring match got this wrong.
        "I don't know the exact term but it uses a hash function to pick a bucket",
        "I don't remember what it's called, though collisions are handled by chaining",
        "A hash function computes the index",
        "Not sure about the load factor, but the hash function gives a bucket index",
        "know",
    ],
)
def test_real_answers_are_not_non_answers(text: str) -> None:
    assert is_non_answer(text) is False


# --------------------------------------------------------------------------
# Feature extraction
# --------------------------------------------------------------------------


def test_feature_vector_matches_declared_order() -> None:
    features = extract_features("a hash function", IDEAL, CONCEPTS, bag_of_words_embedder)
    vector = features.as_vector()
    assert len(vector) == len(FEATURE_ORDER)
    for index, name in enumerate(FEATURE_ORDER):
        assert vector[index] == getattr(features, name)


def test_full_concept_coverage_when_every_concept_present() -> None:
    features = extract_features(IDEAL, IDEAL, CONCEPTS, bag_of_words_embedder)
    assert features.concept_coverage == 1.0
    assert features.semantic_similarity == pytest.approx(1.0)
    assert features.non_answer == 0.0


def test_partial_concept_coverage_is_the_fraction_present() -> None:
    answer = "It uses a hash function to get a bucket index."
    features = extract_features(answer, IDEAL, CONCEPTS, bag_of_words_embedder)
    # "hash function" and "bucket index" present; "collisions", "load factor" absent.
    assert features.concept_coverage == pytest.approx(0.5)


def test_concept_coverage_ignores_word_order_and_connecting_words() -> None:
    """A concept written as "bucket index" should be credited to an answer
    that says "index of the bucket" — the user demonstrated the concept, and
    penalising phrasing would make the feature measure wording, not
    understanding."""
    features = extract_features(
        "it computes the index of the bucket", IDEAL, ["bucket index"], bag_of_words_embedder
    )
    assert features.concept_coverage == 1.0


def test_concept_coverage_matches_simple_plurals() -> None:
    features = extract_features("collision handling", IDEAL, ["collisions"], bag_of_words_embedder)
    assert features.concept_coverage == 1.0


def test_concept_coverage_requires_every_word_of_a_multiword_concept() -> None:
    """"hash" alone must not earn credit for "hash function" — otherwise a
    single common word carries a whole concept, which is how a coverage
    metric becomes meaningless."""
    features = extract_features("something about a hash", IDEAL, ["hash function"], bag_of_words_embedder)
    assert features.concept_coverage == 0.0


def test_no_key_concepts_means_coverage_is_not_penalised() -> None:
    features = extract_features("a real answer here", IDEAL, [], bag_of_words_embedder)
    assert features.concept_coverage == 1.0


def test_non_answer_zeroes_similarity_and_coverage_without_embedding() -> None:
    calls: list[list[str]] = []

    def tracking_embedder(texts: list[str]) -> list[list[float]]:
        calls.append(texts)
        return bag_of_words_embedder(texts)

    features = extract_features("I don't know", IDEAL, CONCEPTS, tracking_embedder)
    assert features.non_answer == 1.0
    assert features.semantic_similarity == 0.0
    assert features.concept_coverage == 0.0
    # The embedder is never called: an empty answer has nothing to embed, and
    # skipping it keeps the common "user gave up" path off the slow path.
    assert calls == []


def test_length_ratio_is_capped() -> None:
    long_answer = " ".join(["word"] * 500)
    features = extract_features(long_answer, IDEAL, CONCEPTS, bag_of_words_embedder)
    assert features.length_ratio == answer_scoring.MAX_LENGTH_RATIO


def test_length_ratio_for_a_short_answer() -> None:
    features = extract_features("hash function", IDEAL, CONCEPTS, bag_of_words_embedder)
    assert 0.0 < features.length_ratio < 0.3


def test_filler_ratio_counts_single_words_and_phrases() -> None:
    plain = extract_features(
        "the hash function computes an index", IDEAL, CONCEPTS, bag_of_words_embedder
    )
    assert plain.filler_ratio == 0.0

    spoken = extract_features(
        "um like basically you know the hash function sort of computes an index",
        IDEAL,
        CONCEPTS,
        bag_of_words_embedder,
    )
    assert spoken.filler_ratio > plain.filler_ratio
    assert 0.0 < spoken.filler_ratio <= 1.0


def test_zero_vectors_do_not_divide_by_zero() -> None:
    features = extract_features("a real answer", IDEAL, CONCEPTS, zero_embedder)
    assert features.semantic_similarity == 0.0


def test_similarity_is_clamped_to_unit_range() -> None:
    """An un-normalized embedder (which a stub has no reason to normalize)
    must not push the feature outside the [0, 1] range the model was fitted
    on."""

    def unnormalized(texts: list[str]) -> list[list[float]]:
        return [[10.0, 10.0, 10.0] for _ in texts]

    features = extract_features("a real answer", IDEAL, CONCEPTS, unnormalized)
    assert 0.0 <= features.semantic_similarity <= 1.0


def test_mismatched_vector_lengths_are_handled() -> None:
    def ragged(texts: list[str]) -> list[list[float]]:
        return [[1.0, 2.0], [1.0, 2.0, 3.0]]

    features = extract_features("a real answer", IDEAL, CONCEPTS, ragged)
    assert features.semantic_similarity == 0.0


# --------------------------------------------------------------------------
# Scoring: the orderings that make the feature defensible
# --------------------------------------------------------------------------


def test_non_answer_scores_zero(force_fallback: None) -> None:
    result = score_answer("How does a hash table work?", "I don't know", IDEAL, CONCEPTS, bag_of_words_embedder)
    assert result.score == 0
    assert result.missed_points == CONCEPTS
    assert "no answer" in result.feedback.lower()


def test_empty_answer_scores_zero(force_fallback: None) -> None:
    result = score_answer("How does a hash table work?", "", IDEAL, CONCEPTS, bag_of_words_embedder)
    assert result.score == 0


def test_complete_answer_scores_higher_than_partial_than_off_topic(force_fallback: None) -> None:
    question = "How does a hash table work?"
    off_topic = (
        "Photosynthesis uses chlorophyll in the chloroplast to absorb light, "
        "and the Calvin cycle fixes carbon dioxide into glucose."
    )

    complete = score_answer(question, IDEAL, IDEAL, CONCEPTS, bag_of_words_embedder).score
    partial = score_answer(
        question, "It uses a hash function to get a bucket index.", IDEAL, CONCEPTS, bag_of_words_embedder
    ).score
    unrelated = score_answer(question, off_topic, IDEAL, CONCEPTS, bag_of_words_embedder).score

    assert complete > partial > unrelated
    assert complete >= 70
    assert unrelated <= 30


def test_scoring_is_deterministic(force_fallback: None) -> None:
    """The headline reason this isn't an LLM call: the same answer must score
    identically every time, or the feature can't be trusted or tested."""
    args = ("How does a hash table work?", "A hash function computes a bucket index.", IDEAL, CONCEPTS)
    first = score_answer(*args, bag_of_words_embedder)
    second = score_answer(*args, bag_of_words_embedder)
    assert first.score == second.score
    assert first.features == second.features
    assert first.feedback == second.feedback


def test_score_is_always_within_range(force_fallback: None) -> None:
    for answer in ["", "x", IDEAL, IDEAL * 5, "um uh like basically you know"]:
        result = score_answer("q", answer, IDEAL, CONCEPTS, bag_of_words_embedder)
        assert 0 <= result.score <= 100


def test_missed_points_name_the_absent_concepts(force_fallback: None) -> None:
    result = score_answer(
        "How does a hash table work?",
        "It uses a hash function to get a bucket index.",
        IDEAL,
        CONCEPTS,
        bag_of_words_embedder,
    )
    assert "collisions" in result.missed_points
    assert "load factor" in result.missed_points
    assert "hash function" not in result.missed_points


def test_feedback_mentions_missed_concepts(force_fallback: None) -> None:
    result = score_answer(
        "How does a hash table work?",
        "It uses a hash function.",
        IDEAL,
        CONCEPTS,
        bag_of_words_embedder,
    )
    assert "Not mentioned" in result.feedback


def test_features_are_reported_alongside_the_score(force_fallback: None) -> None:
    """A score the UI can explain is the whole design goal, so the feature
    breakdown travels with it rather than being recomputed or guessed at."""
    result = score_answer("q", "A hash function computes a bucket index.", IDEAL, CONCEPTS, bag_of_words_embedder)
    assert set(result.features) == set(FEATURE_ORDER)
    assert all(isinstance(value, float) for value in result.features.values())


def test_filler_heavy_answer_scores_below_the_same_answer_without_filler(force_fallback: None) -> None:
    clean = "A hash function computes a bucket index and collisions are resolved by chaining."
    spoken = (
        "um so like basically a hash function sort of computes a bucket index you know "
        "and um collisions are like resolved by chaining i mean"
    )
    assert (
        score_answer("q", clean, IDEAL, CONCEPTS, bag_of_words_embedder).score
        >= score_answer("q", spoken, IDEAL, CONCEPTS, bag_of_words_embedder).score
    )


# --------------------------------------------------------------------------
# Fallback behaviour: the app must never hard-fail on a missing model file
# --------------------------------------------------------------------------


def test_missing_artefact_falls_back_rather_than_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(answer_scoring, "MODEL_PATH", answer_scoring.MODEL_PATH.with_name("nope.joblib"))
    answer_scoring._load_model.cache_clear()

    result = score_answer("q", IDEAL, IDEAL, CONCEPTS, bag_of_words_embedder)
    assert result.used_fallback is True
    assert result.score > 0


def test_corrupted_artefact_falls_back_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    broken = tmp_path / "answer_scorer.joblib"
    broken.write_bytes(b"this is not a joblib file")
    monkeypatch.setattr(answer_scoring, "MODEL_PATH", broken)
    answer_scoring._load_model.cache_clear()

    result = score_answer("q", IDEAL, IDEAL, CONCEPTS, bag_of_words_embedder)
    assert result.used_fallback is True
    assert result.score > 0


def test_a_predict_failure_falls_back_rather_than_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    class ExplodingModel:
        def predict(self, _rows):
            raise RuntimeError("sklearn version mismatch")

    monkeypatch.setattr(answer_scoring, "_load_model", lambda: ExplodingModel())

    result = score_answer("q", IDEAL, IDEAL, CONCEPTS, bag_of_words_embedder)
    assert result.used_fallback is True
    assert result.score > 0


def test_a_model_predicting_out_of_range_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    class WildModel:
        def predict(self, _rows):
            return [410.0]

    monkeypatch.setattr(answer_scoring, "_load_model", lambda: WildModel())

    result = score_answer("q", IDEAL, IDEAL, CONCEPTS, bag_of_words_embedder)
    assert result.score == 100
    assert result.used_fallback is False


def test_fallback_orders_the_quality_tiers_correctly() -> None:
    """The fallback is only useful if it preserves the ordering the trained
    model provides. A fallback that scored an off-topic answer above a
    partial one would be worse than no fallback at all."""
    features_complete = AnswerFeatures(0.95, 1.0, 1.0, 0.0, 0.0)
    features_partial = AnswerFeatures(0.6, 0.5, 0.6, 0.05, 0.0)
    features_off_topic = AnswerFeatures(0.2, 0.0, 1.2, 0.0, 0.0)
    features_non_answer = AnswerFeatures(0.0, 0.0, 0.0, 0.0, 1.0)

    complete = answer_scoring._fallback_score(features_complete)
    partial = answer_scoring._fallback_score(features_partial)
    off_topic = answer_scoring._fallback_score(features_off_topic)
    non_answer = answer_scoring._fallback_score(features_non_answer)

    assert complete > partial > off_topic > non_answer
    assert non_answer == 0.0
    assert complete <= 100.0


# --------------------------------------------------------------------------
# The committed artefact itself
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    not answer_scoring.MODEL_PATH.exists(),
    reason="trained artefact not present in this checkout",
)
def test_committed_artefact_loads_and_orders_the_tiers() -> None:
    """Guards the committed model, not just the code around it: an artefact
    that loads but scores an off-topic answer above a complete one would pass
    every other test in this file."""
    answer_scoring._load_model.cache_clear()
    question = "How does a hash table work?"
    off_topic = (
        "Photosynthesis uses chlorophyll in the chloroplast to absorb light, "
        "and the Calvin cycle fixes carbon dioxide into glucose."
    )

    complete = score_answer(question, IDEAL, IDEAL, CONCEPTS, bag_of_words_embedder)
    partial = score_answer(
        question, "It uses a hash function to get a bucket index.", IDEAL, CONCEPTS, bag_of_words_embedder
    )
    unrelated = score_answer(question, off_topic, IDEAL, CONCEPTS, bag_of_words_embedder)

    assert complete.used_fallback is False
    assert complete.score > partial.score > unrelated.score


@pytest.mark.skipif(
    not answer_scoring.METRICS_PATH.exists(),
    reason="metrics file not present in this checkout",
)
def test_committed_metrics_report_held_out_performance() -> None:
    metrics = answer_scoring.load_metrics()
    assert metrics is not None
    assert "held_out_mae" in metrics
    assert "held_out_r2" in metrics
    assert metrics["feature_order"] == list(FEATURE_ORDER)
    # A sanity bound, not a tight one: the point is to catch an artefact
    # trained on a broken corpus, not to chase a specific number.
    assert metrics["held_out_mae"] < 20
    assert not math.isnan(float(metrics["held_out_r2"]))


def test_load_metrics_returns_none_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(answer_scoring, "METRICS_PATH", answer_scoring.METRICS_PATH.with_name("nope.json"))
    assert answer_scoring.load_metrics() is None
