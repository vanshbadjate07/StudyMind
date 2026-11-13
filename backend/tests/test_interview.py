"""Tests for the interview agent's decision loop (PRD 6.7).

These are the tests that matter most for this feature: the adaptive
questioning IS the feature, so it's tested directly as a pure function
against constructed turn histories - no LLM, no database, no scoring model.
If this logic is right, the interview adapts; if it isn't, the feature is a
quiz with extra steps.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.config import settings
from app.models import InterviewQA
from app.services.interview import decide_next_step, summarize_session

TOPICS = ["Hash tables", "Processes and threads", "Normalization"]

LOW = settings.interview_low_score_threshold


def qa(
    index: int,
    topic: str | None,
    score: int | None = None,
    *,
    answered: bool = True,
    is_probe: bool = False,
    missed: list[str] | None = None,
) -> InterviewQA:
    """Builds an unattached InterviewQA. Not persisted on purpose - the
    decision loop reads only these fields, so a real session would add
    nothing but slowness."""
    import json

    return InterviewQA(
        session_id="s1",
        question_index=index,
        topic=topic,
        question=f"Question {index}?",
        ideal_answer="The ideal answer.",
        key_concepts_json=json.dumps(["concept one", "concept two"]),
        is_probe=is_probe,
        score=score,
        missed_points_json=json.dumps(missed) if missed else None,
        answered_at=(datetime.now(UTC) + timedelta(seconds=index)) if answered else None,
    )


# ---------------------------------------------------------------------------
# Opening move
# ---------------------------------------------------------------------------


def test_first_step_takes_the_first_topic() -> None:
    step = decide_next_step(TOPICS, [], question_limit=8)
    assert step is not None
    assert step.topic == "Hash tables"
    assert step.is_probe is False


def test_no_agenda_still_produces_a_step() -> None:
    """Thin material can yield no topic list. The interview must still run,
    asking against the notebook as a whole, rather than refusing to start."""
    step = decide_next_step([], [], question_limit=8)
    assert step is not None
    assert step.topic is None
    assert step.is_probe is False


# ---------------------------------------------------------------------------
# Advancing on a good answer
# ---------------------------------------------------------------------------


def test_strong_answer_advances_to_the_next_topic() -> None:
    history = [qa(0, "Hash tables", score=85)]
    step = decide_next_step(TOPICS, history, question_limit=8)
    assert step is not None
    assert step.topic == "Processes and threads"
    assert step.is_probe is False


def test_answer_exactly_at_the_threshold_advances() -> None:
    """The threshold is the boundary of "weak", so a score sitting on it is
    not weak. Pinned because an off-by-one here silently turns every
    borderline answer into a probe."""
    history = [qa(0, "Hash tables", score=LOW)]
    step = decide_next_step(TOPICS, history, question_limit=8)
    assert step is not None
    assert step.topic == "Processes and threads"
    assert step.is_probe is False


def test_advancing_skips_topics_already_covered() -> None:
    history = [
        qa(0, "Hash tables", score=90),
        qa(1, "Processes and threads", score=88),
    ]
    step = decide_next_step(TOPICS, history, question_limit=8)
    assert step is not None
    assert step.topic == "Normalization"


# ---------------------------------------------------------------------------
# Probing on a weak answer - the heart of the feature
# ---------------------------------------------------------------------------


def test_weak_answer_probes_the_same_topic() -> None:
    history = [qa(0, "Hash tables", score=LOW - 1, missed=["collisions", "load factor"])]
    step = decide_next_step(TOPICS, history, question_limit=8)
    assert step is not None
    assert step.topic == "Hash tables"
    assert step.is_probe is True
    assert step.probing_after is history[0]


def test_two_consecutive_weak_answers_abandon_the_topic_and_move_on() -> None:
    """The cap that stops an adaptive interview being worse than a fixed
    list: without it, a topic the candidate doesn't know absorbs every
    remaining question."""
    history = [
        qa(0, "Hash tables", score=20),
        qa(1, "Hash tables", score=15, is_probe=True),
    ]
    step = decide_next_step(TOPICS, history, question_limit=8)
    assert step is not None
    assert step.topic == "Processes and threads"
    assert step.is_probe is False


def test_recovering_on_a_probe_advances_normally() -> None:
    history = [
        qa(0, "Hash tables", score=30),
        qa(1, "Hash tables", score=75, is_probe=True),
    ]
    step = decide_next_step(TOPICS, history, question_limit=8)
    assert step is not None
    assert step.topic == "Processes and threads"
    assert step.is_probe is False


def test_weak_streak_is_counted_per_topic_not_globally() -> None:
    """A weak answer on an earlier, different topic must not count toward the
    current topic's streak - otherwise a candidate who struggled once early
    gets no probe at all later."""
    history = [
        qa(0, "Hash tables", score=10),
        qa(1, "Processes and threads", score=12),
    ]
    step = decide_next_step(TOPICS, history, question_limit=8)
    assert step is not None
    assert step.topic == "Processes and threads"
    assert step.is_probe is True


def test_an_earlier_weak_answer_on_the_same_topic_does_not_inflate_the_streak() -> None:
    """The streak is the run at the tail. A weak answer on this topic, then a
    good one, then a weak one, is a streak of 1 - so it still earns a probe."""
    history = [
        qa(0, "Hash tables", score=10),
        qa(1, "Hash tables", score=80, is_probe=True),
        qa(2, "Hash tables", score=20),
    ]
    step = decide_next_step(TOPICS, history, question_limit=8)
    assert step is not None
    assert step.topic == "Hash tables"
    assert step.is_probe is True


def test_weak_answer_with_no_agenda_still_probes() -> None:
    history = [qa(0, None, score=10)]
    step = decide_next_step([], history, question_limit=8)
    assert step is not None
    assert step.topic is None
    assert step.is_probe is True


# ---------------------------------------------------------------------------
# Finishing
# ---------------------------------------------------------------------------


def test_finishes_when_the_question_limit_is_reached() -> None:
    history = [qa(i, TOPICS[i % len(TOPICS)], score=80) for i in range(4)]
    assert decide_next_step(TOPICS, history, question_limit=4) is None


def test_limit_counts_asked_questions_not_answered_ones() -> None:
    """An unanswered question still occupies a slot. Counting only answered
    ones would let the interview ask limit+1 questions."""
    history = [
        qa(0, "Hash tables", score=80),
        qa(1, "Processes and threads", answered=False),
    ]
    assert decide_next_step(TOPICS, history, question_limit=2) is None


def test_finishes_when_every_topic_has_been_covered() -> None:
    history = [qa(i, topic, score=80) for i, topic in enumerate(TOPICS)]
    assert decide_next_step(TOPICS, history, question_limit=20) is None


def test_abandoned_topic_still_counts_as_covered_when_finishing() -> None:
    """A topic given up on after two weak answers must not be re-offered as
    "uncovered" - that would loop the interview back onto it forever."""
    history = [
        qa(0, "Hash tables", score=10),
        qa(1, "Hash tables", score=10, is_probe=True),
        qa(2, "Processes and threads", score=80),
        qa(3, "Normalization", score=80),
    ]
    assert decide_next_step(TOPICS, history, question_limit=20) is None


def test_an_unanswered_pending_question_does_not_drive_a_decision() -> None:
    """decide_next_step is only ever called with the pending turn already
    answered, but if a pending turn did leak in it must not be read as a
    weak answer (score is None) and trigger a spurious probe."""
    history = [
        qa(0, "Hash tables", score=90),
        qa(1, "Processes and threads", answered=False),
    ]
    step = decide_next_step(TOPICS, history, question_limit=8)
    assert step is not None
    assert step.is_probe is False
    assert step.topic == "Normalization"


# ---------------------------------------------------------------------------
# The final report
# ---------------------------------------------------------------------------


def test_summary_of_an_empty_session_is_empty() -> None:
    assert summarize_session(TOPICS, []) == (None, [])


def test_summary_ignores_unanswered_questions() -> None:
    history = [qa(0, "Hash tables", score=80), qa(1, "Normalization", answered=False)]
    overall, weak = summarize_session(TOPICS, history)
    assert overall == 80
    assert weak == []


def test_overall_score_is_the_mean_of_answers() -> None:
    history = [
        qa(0, "Hash tables", score=90),
        qa(1, "Processes and threads", score=60),
        qa(2, "Normalization", score=30),
    ]
    overall, _ = summarize_session(TOPICS, history)
    assert overall == 60


def test_weak_areas_are_topics_whose_answers_average_below_the_threshold() -> None:
    history = [
        qa(0, "Hash tables", score=90),
        qa(1, "Processes and threads", score=20),
        qa(2, "Processes and threads", score=25, is_probe=True),
    ]
    _, weak = summarize_session(TOPICS, history)
    assert weak == ["Processes and threads"]


def test_one_bad_answer_on_an_otherwise_strong_topic_is_not_a_weak_area() -> None:
    """Averaging rather than flagging any single weak answer. Flagging every
    dip would make the report noisy enough that nobody reads it."""
    history = [
        qa(0, "Hash tables", score=30),
        qa(1, "Hash tables", score=95, is_probe=True),
    ]
    _, weak = summarize_session(TOPICS, history)
    assert weak == []


def test_weak_areas_are_reported_in_agenda_order() -> None:
    history = [
        qa(0, "Normalization", score=10),
        qa(1, "Hash tables", score=10),
    ]
    _, weak = summarize_session(TOPICS, history)
    assert weak == ["Hash tables", "Normalization"]


def test_untopiced_answers_are_never_reported_as_weak_areas() -> None:
    """With no agenda there's no topic name to show the user, so a weak run
    produces a low overall score and no named weak area - rather than a
    report with a blank or null entry in it."""
    history = [qa(0, None, score=5), qa(1, None, score=5)]
    overall, weak = summarize_session([], history)
    assert overall == 5
    assert weak == []


@pytest.mark.parametrize("limit", [3, 8, 20])
def test_a_full_run_always_terminates(limit: int) -> None:
    """Property check on the loop as a whole: whatever the candidate does,
    the interview must end. A probe branch that could re-fire indefinitely is
    the one bug in this logic that would hang the feature rather than just
    answer oddly - so this simulates the worst case (every answer weak) and
    asserts termination within the limit."""
    history: list[InterviewQA] = []
    for _ in range(limit + 5):
        step = decide_next_step(TOPICS, history, question_limit=limit)
        if step is None:
            break
        history.append(qa(len(history), step.topic, score=0, is_probe=step.is_probe))
    else:  # pragma: no cover - only reached if the loop never terminates
        pytest.fail("decide_next_step never returned None")

    assert len(history) <= limit
    assert decide_next_step(TOPICS, history, question_limit=limit) is None
