"""API-level tests for the mock interview (PRD 6.7).

The decision loop itself is tested as a pure function in test_interview.py.
This file exercises the HTTP path: state transitions, the error cases, and
that the agent's adaptation actually survives the round trip through the
database rather than only holding in the unit tests.
"""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import InterviewQA, InterviewSession, Overview, OverviewStatus
from app.services.answer_scoring import AnswerScore

FIXTURES = Path(__file__).parent / "fixtures"

ANSWER_TEXT = "A hash function computes a bucket index, and collisions are resolved by chaining."


class _FakeInterviewClient:
    """Answers both prompts the interview makes: the topic-agenda prompt and
    the per-question prompt, told apart by the JSON shape each asks for."""

    def __init__(self, topics: list[str] | None = None) -> None:
        self.topics = ["Hash tables", "Processes and threads"] if topics is None else topics
        self.prompts: list[str] = []
        self.questions_asked = 0

    async def generate_json(self, prompt: str, *, temperature: float = 0.2) -> str:
        self.prompts.append(prompt)
        if '"topics"' in prompt:
            return json.dumps({"topics": self.topics})
        self.questions_asked += 1
        return json.dumps(
            {
                "question": f"Question {self.questions_asked}?",
                "ideal_answer": ANSWER_TEXT,
                "key_concepts": ["hash function", "bucket index"],
            }
        )

    async def generate_text(self, prompt: str, *, temperature: float = 0.3) -> str:
        # The interview only ever asks for structured JSON. If this fires,
        # something started generating prose where a schema was expected.
        raise AssertionError("the interview should not call generate_text")


class _BrokenClient:
    async def generate_json(self, prompt: str, *, temperature: float = 0.2) -> str:
        from app.services.llm_errors import LLMUnreachableError

        raise LLMUnreachableError("no provider reachable")

    async def generate_text(self, prompt: str, *, temperature: float = 0.3) -> str:
        from app.services.llm_errors import LLMUnreachableError

        raise LLMUnreachableError("no provider reachable")


def _use_client(monkeypatch, fake) -> None:
    monkeypatch.setattr("app.services.llm_client.OllamaClient", lambda *a, **k: fake)


def _fixed_scorer(score: int, missed: list[str] | None = None):
    """Replaces the trained scorer so a test can drive the agent down a
    specific branch. The scorer has its own tests; here the point is which
    branch the agent takes given a score, not what the score should be."""

    def _scorer(question, user_answer, ideal_answer, key_concepts, embedder=None):  # noqa: ANN001
        return AnswerScore(
            score=score,
            missed_points=missed or [],
            feedback="Fixed feedback for this test.",
            features={"semantic_similarity": 0.5, "concept_coverage": 0.5},
            used_fallback=False,
        )

    return _scorer


def _create_notebook(client: TestClient, name: str = "Interview Notebook") -> str:
    return client.post("/notebooks", json={"name": name}).json()["id"]


def _upload_ready_document(client: TestClient, notebook_id: str) -> str:
    data = (FIXTURES / "normal.pdf").read_bytes()
    response = client.post(
        f"/notebooks/{notebook_id}/documents",
        files={"file": ("normal.pdf", data, "application/pdf")},
    )
    document_id = response.json()["id"]
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        body = client.get(f"/documents/{document_id}").json()
        if body["status"] == "ready":
            return document_id
        if body["status"] == "failed":
            raise AssertionError(f"fixture document failed to process: {body['error_reason']}")
        time.sleep(0.05)
    raise TimeoutError("fixture document never became ready")


def _notebook_with_material(client: TestClient) -> str:
    notebook_id = _create_notebook(client)
    _upload_ready_document(client, notebook_id)
    return notebook_id


# ---------------------------------------------------------------------------
# Reading before anything exists
# ---------------------------------------------------------------------------


def test_get_latest_404_when_notebook_missing(client: TestClient) -> None:
    assert client.get("/notebooks/does-not-exist/interview").status_code == 404


def test_get_latest_404_before_any_interview(client: TestClient) -> None:
    notebook_id = _create_notebook(client)
    assert client.get(f"/notebooks/{notebook_id}/interview").status_code == 404


def test_start_404_when_notebook_missing(client: TestClient) -> None:
    assert client.post("/notebooks/does-not-exist/interview/start").status_code == 404


def test_start_409_without_ready_documents(client: TestClient) -> None:
    notebook_id = _create_notebook(client)
    response = client.post(f"/notebooks/{notebook_id}/interview/start")
    assert response.status_code == 409
    assert "ready documents" in response.json()["detail"]


def test_get_session_404_when_missing(client: TestClient) -> None:
    assert client.get("/interview/does-not-exist").status_code == 404


# ---------------------------------------------------------------------------
# Starting
# ---------------------------------------------------------------------------


def test_start_returns_the_first_question(client: TestClient, monkeypatch) -> None:
    _use_client(monkeypatch, _FakeInterviewClient())
    notebook_id = _notebook_with_material(client)

    response = client.post(f"/notebooks/{notebook_id}/interview/start", json={"question_limit": 5})
    assert response.status_code == 201
    body = response.json()

    assert body["status"] == "in_progress"
    assert body["mode"] == "text"
    assert body["question_limit"] == 5
    assert body["overall_score"] is None
    assert body["answered_count"] == 0
    assert len(body["turns"]) == 1
    assert body["current_question"]["question"] == "Question 1?"
    assert body["current_question"]["is_probe"] is False
    assert body["current_question"]["key_concepts"] == ["hash function", "bucket index"]


def test_start_hides_the_ideal_answer_until_the_question_is_answered(
    client: TestClient, monkeypatch
) -> None:
    """Showing the model answer next to an unanswered question would just be
    handing over the answer key."""
    _use_client(monkeypatch, _FakeInterviewClient())
    notebook_id = _notebook_with_material(client)

    body = client.post(f"/notebooks/{notebook_id}/interview/start").json()
    assert body["current_question"]["ideal_answer"] is None


def test_start_with_no_body_uses_defaults(client: TestClient, monkeypatch) -> None:
    _use_client(monkeypatch, _FakeInterviewClient())
    notebook_id = _notebook_with_material(client)

    body = client.post(f"/notebooks/{notebook_id}/interview/start").json()
    assert body["question_limit"] == 8


def test_start_409_when_one_is_already_in_progress(client: TestClient, monkeypatch) -> None:
    """An in-progress interview is work the user did; a second start must not
    silently discard it."""
    _use_client(monkeypatch, _FakeInterviewClient())
    notebook_id = _notebook_with_material(client)

    assert client.post(f"/notebooks/{notebook_id}/interview/start").status_code == 201
    second = client.post(f"/notebooks/{notebook_id}/interview/start")
    assert second.status_code == 409
    assert "already in progress" in second.json()["detail"]


def test_start_can_begin_a_new_interview_after_the_previous_one_ended(
    client: TestClient, monkeypatch
) -> None:
    """Interviews are repeatable - unlike quiz/overview there is no one-row
    -per-notebook constraint to trip over on the second run."""
    _use_client(monkeypatch, _FakeInterviewClient())
    notebook_id = _notebook_with_material(client)

    first_id = client.post(f"/notebooks/{notebook_id}/interview/start").json()["id"]
    client.post(f"/interview/{first_id}/end")

    second = client.post(f"/notebooks/{notebook_id}/interview/start")
    assert second.status_code == 201
    assert second.json()["id"] != first_id


def test_start_503_and_persists_nothing_when_the_llm_is_down(
    client: TestClient, monkeypatch
) -> None:
    _use_client(monkeypatch, _BrokenClient())
    notebook_id = _notebook_with_material(client)

    response = client.post(f"/notebooks/{notebook_id}/interview/start")
    assert response.status_code == 503
    # A failed start must not leave an empty session in the notebook's history.
    assert client.get(f"/notebooks/{notebook_id}/interview").status_code == 404


@pytest.mark.asyncio
async def test_topics_come_from_the_notebook_overview_when_one_is_ready(
    client: TestClient, monkeypatch
) -> None:
    """Reusing the overview's topic breakdown (PRD 6.2) means the interview
    covers the ground the user was already shown, instead of inventing a
    second view of the same material."""
    fake = _FakeInterviewClient(topics=["Should not be used"])
    _use_client(monkeypatch, fake)
    notebook_id = _notebook_with_material(client)

    async with client.test_session_factory() as db:
        result = await db.execute(select(Overview).where(Overview.notebook_id == notebook_id))
        overview = result.scalar_one_or_none()
        topics = [
            {"title": "Overview topic one", "summary": "s", "key_concepts": ["c"]},
            {"title": "Overview topic two", "summary": "s", "key_concepts": ["c"]},
        ]
        if overview is None:
            db.add(
                Overview(
                    notebook_id=notebook_id,
                    status=OverviewStatus.READY,
                    short_summary="A summary.",
                    topics_json=json.dumps(topics),
                    estimated_minutes=30,
                )
            )
        else:
            overview.status = OverviewStatus.READY
            overview.topics_json = json.dumps(topics)
            overview.short_summary = "A summary."
        await db.commit()

    body = client.post(f"/notebooks/{notebook_id}/interview/start").json()
    assert body["topics"] == ["Overview topic one", "Overview topic two"]
    assert body["current_question"]["topic"] == "Overview topic one"


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------


def test_answering_scores_the_turn_and_asks_the_next_question(
    client: TestClient, monkeypatch
) -> None:
    _use_client(monkeypatch, _FakeInterviewClient())
    monkeypatch.setattr("app.services.interview.score_answer", _fixed_scorer(82))
    notebook_id = _notebook_with_material(client)
    interview_id = client.post(f"/notebooks/{notebook_id}/interview/start").json()["id"]

    response = client.post(f"/interview/{interview_id}/answer", json={"answer": ANSWER_TEXT})
    assert response.status_code == 200
    body = response.json()

    first = body["turns"][0]
    assert first["score"] == 82
    assert first["answer_text"] == ANSWER_TEXT
    assert first["feedback"] == "Fixed feedback for this test."
    assert first["answered_at"] is not None
    # The model answer is released only now that the user has committed to theirs.
    assert first["ideal_answer"] == ANSWER_TEXT
    assert first["features"]["concept_coverage"] == 0.5

    assert body["answered_count"] == 1
    assert body["status"] == "in_progress"
    assert body["current_question"]["question"] == "Question 2?"


def test_a_weak_answer_probes_the_same_topic(client: TestClient, monkeypatch) -> None:
    """The adaptation, verified through the full HTTP and database round
    trip rather than only as a pure function."""
    _use_client(monkeypatch, _FakeInterviewClient())
    monkeypatch.setattr(
        "app.services.interview.score_answer", _fixed_scorer(18, missed=["collisions"])
    )
    notebook_id = _notebook_with_material(client)
    start = client.post(f"/notebooks/{notebook_id}/interview/start").json()
    first_topic = start["current_question"]["topic"]

    body = client.post(f"/interview/{start['id']}/answer", json={"answer": "Not sure"}).json()

    assert body["current_question"]["is_probe"] is True
    assert body["current_question"]["topic"] == first_topic


def test_a_strong_answer_moves_to_a_new_topic(client: TestClient, monkeypatch) -> None:
    _use_client(monkeypatch, _FakeInterviewClient())
    monkeypatch.setattr("app.services.interview.score_answer", _fixed_scorer(90))
    notebook_id = _notebook_with_material(client)
    start = client.post(f"/notebooks/{notebook_id}/interview/start").json()
    first_topic = start["current_question"]["topic"]

    body = client.post(f"/interview/{start['id']}/answer", json={"answer": ANSWER_TEXT}).json()

    assert body["current_question"]["is_probe"] is False
    assert body["current_question"]["topic"] != first_topic


def test_the_probe_prompt_tells_the_model_what_was_missed(
    client: TestClient, monkeypatch
) -> None:
    """A probe is only a real probe if the gap reaches the prompt - otherwise
    it's just another question on the same topic."""
    fake = _FakeInterviewClient()
    _use_client(monkeypatch, fake)
    monkeypatch.setattr(
        "app.services.interview.score_answer", _fixed_scorer(12, missed=["load factor"])
    )
    notebook_id = _notebook_with_material(client)
    start = client.post(f"/notebooks/{notebook_id}/interview/start").json()

    client.post(f"/interview/{start['id']}/answer", json={"answer": "No idea"})

    probe_prompt = fake.prompts[-1]
    assert "load factor" in probe_prompt
    assert "SIMPLER" in probe_prompt
    assert "Question 1?" in probe_prompt  # told not to repeat the previous question


def test_an_empty_answer_is_accepted_and_scored_zero(client: TestClient, monkeypatch) -> None:
    """Skipping a question is a real event the report should carry, not a
    422 the user has to work around."""
    _use_client(monkeypatch, _FakeInterviewClient())
    notebook_id = _notebook_with_material(client)
    interview_id = client.post(f"/notebooks/{notebook_id}/interview/start").json()["id"]

    response = client.post(f"/interview/{interview_id}/answer", json={"answer": ""})
    assert response.status_code == 200
    assert response.json()["turns"][0]["score"] == 0


def test_answer_404_when_the_interview_is_missing(client: TestClient) -> None:
    response = client.post("/interview/does-not-exist/answer", json={"answer": "x"})
    assert response.status_code == 404


def test_real_scorer_runs_end_to_end(client: TestClient, monkeypatch) -> None:
    """One test with the actual trained scorer and the real embedder wired
    in, so the integration is proven rather than mocked away everywhere."""
    _use_client(monkeypatch, _FakeInterviewClient())
    notebook_id = _notebook_with_material(client)
    interview_id = client.post(f"/notebooks/{notebook_id}/interview/start").json()["id"]

    good = client.post(f"/interview/{interview_id}/answer", json={"answer": ANSWER_TEXT}).json()
    score = good["turns"][0]["score"]

    assert 0 <= score <= 100
    # An answer identical to the ideal answer must score well under the real
    # model; a near-zero here would mean the feature pipeline is misreporting.
    assert score >= 60
    assert set(good["turns"][0]["features"]) >= {"semantic_similarity", "concept_coverage"}


# ---------------------------------------------------------------------------
# Completion and the report
# ---------------------------------------------------------------------------


def test_interview_completes_at_the_question_limit_with_a_report(
    client: TestClient, monkeypatch
) -> None:
    # More topics than the question limit, so the LIMIT is what ends the
    # interview. With fewer topics than the limit, "every topic covered" ends
    # it first - which is correct behaviour, but a different code path, and
    # the one the next test covers.
    _use_client(
        monkeypatch, _FakeInterviewClient(topics=["T one", "T two", "T three", "T four", "T five"])
    )
    monkeypatch.setattr("app.services.interview.score_answer", _fixed_scorer(70))
    notebook_id = _notebook_with_material(client)
    interview_id = client.post(
        f"/notebooks/{notebook_id}/interview/start", json={"question_limit": 3}
    ).json()["id"]

    body = None
    for _ in range(3):
        body = client.post(f"/interview/{interview_id}/answer", json={"answer": ANSWER_TEXT}).json()

    assert body is not None
    assert body["status"] == "completed"
    assert body["overall_score"] == 70
    assert body["answered_count"] == 3
    assert len(body["turns"]) == 3
    assert body["current_question"] is None
    assert body["completed_at"] is not None


def test_interview_completes_early_when_every_topic_is_covered(
    client: TestClient, monkeypatch
) -> None:
    """The other termination path: a short agenda finishes the interview
    before the question limit, rather than looping back for second passes."""
    _use_client(monkeypatch, _FakeInterviewClient(topics=["Only topic"]))
    monkeypatch.setattr("app.services.interview.score_answer", _fixed_scorer(88))
    notebook_id = _notebook_with_material(client)
    interview_id = client.post(
        f"/notebooks/{notebook_id}/interview/start", json={"question_limit": 20}
    ).json()["id"]

    body = client.post(f"/interview/{interview_id}/answer", json={"answer": ANSWER_TEXT}).json()

    assert body["status"] == "completed"
    assert body["answered_count"] == 1
    assert body["overall_score"] == 88
    assert body["current_question"] is None


def test_weak_topics_are_flagged_in_the_completed_report(
    client: TestClient, monkeypatch
) -> None:
    _use_client(monkeypatch, _FakeInterviewClient(topics=["Hash tables", "Threads"]))
    monkeypatch.setattr("app.services.interview.score_answer", _fixed_scorer(10))
    notebook_id = _notebook_with_material(client)
    interview_id = client.post(
        f"/notebooks/{notebook_id}/interview/start", json={"question_limit": 3}
    ).json()["id"]

    body = None
    for _ in range(3):
        response = client.post(f"/interview/{interview_id}/answer", json={"answer": "no idea"})
        body = response.json()
        if body["status"] == "completed":
            break

    assert body is not None
    assert body["status"] == "completed"
    assert body["overall_score"] == 10
    assert "Hash tables" in body["weak_areas"]


def test_answering_a_completed_interview_409s(client: TestClient, monkeypatch) -> None:
    _use_client(monkeypatch, _FakeInterviewClient())
    monkeypatch.setattr("app.services.interview.score_answer", _fixed_scorer(70))
    notebook_id = _notebook_with_material(client)
    interview_id = client.post(
        f"/notebooks/{notebook_id}/interview/start", json={"question_limit": 3}
    ).json()["id"]
    for _ in range(3):
        client.post(f"/interview/{interview_id}/answer", json={"answer": ANSWER_TEXT})

    response = client.post(f"/interview/{interview_id}/answer", json={"answer": "late"})
    assert response.status_code == 409
    assert "already finished" in response.json()["detail"]


def test_ending_early_still_produces_a_report(client: TestClient, monkeypatch) -> None:
    _use_client(monkeypatch, _FakeInterviewClient())
    monkeypatch.setattr("app.services.interview.score_answer", _fixed_scorer(64))
    notebook_id = _notebook_with_material(client)
    interview_id = client.post(
        f"/notebooks/{notebook_id}/interview/start", json={"question_limit": 8}
    ).json()["id"]
    client.post(f"/interview/{interview_id}/answer", json={"answer": ANSWER_TEXT})

    body = client.post(f"/interview/{interview_id}/end").json()
    assert body["status"] == "completed"
    assert body["overall_score"] == 64
    assert body["answered_count"] == 1
    assert body["completed_at"] is not None


def test_ending_an_interview_with_no_answers_reports_no_score(
    client: TestClient, monkeypatch
) -> None:
    _use_client(monkeypatch, _FakeInterviewClient())
    notebook_id = _notebook_with_material(client)
    interview_id = client.post(f"/notebooks/{notebook_id}/interview/start").json()["id"]

    body = client.post(f"/interview/{interview_id}/end").json()
    assert body["status"] == "completed"
    assert body["overall_score"] is None
    assert body["weak_areas"] == []


def test_ending_twice_is_harmless(client: TestClient, monkeypatch) -> None:
    _use_client(monkeypatch, _FakeInterviewClient())
    notebook_id = _notebook_with_material(client)
    interview_id = client.post(f"/notebooks/{notebook_id}/interview/start").json()["id"]

    first = client.post(f"/interview/{interview_id}/end").json()
    second = client.post(f"/interview/{interview_id}/end")
    assert second.status_code == 200
    assert second.json()["completed_at"] == first["completed_at"]


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


def test_continue_does_not_queue_a_second_question(client: TestClient, monkeypatch) -> None:
    _use_client(monkeypatch, _FakeInterviewClient())
    notebook_id = _notebook_with_material(client)
    interview_id = client.post(f"/notebooks/{notebook_id}/interview/start").json()["id"]

    body = client.post(f"/interview/{interview_id}/continue").json()
    assert len(body["turns"]) == 1


@pytest.mark.asyncio
async def test_continue_recovers_an_interview_left_with_no_pending_question(
    client: TestClient, monkeypatch
) -> None:
    """The failure this endpoint exists for: the answer was scored and
    committed, then generating the next question failed. The interview must
    be resumable rather than stranded."""
    _use_client(monkeypatch, _FakeInterviewClient())
    monkeypatch.setattr("app.services.interview.score_answer", _fixed_scorer(80))
    notebook_id = _notebook_with_material(client)
    interview_id = client.post(f"/notebooks/{notebook_id}/interview/start").json()["id"]
    client.post(f"/interview/{interview_id}/answer", json={"answer": ANSWER_TEXT})

    # Simulate the crash window by removing the unanswered question that the
    # successful call just created.
    async with client.test_session_factory() as db:
        result = await db.execute(
            select(InterviewQA).where(
                InterviewQA.session_id == interview_id, InterviewQA.answered_at.is_(None)
            )
        )
        for row in result.scalars().all():
            await db.delete(row)
        await db.commit()

    stranded = client.get(f"/interview/{interview_id}").json()
    assert stranded["current_question"] is None
    assert stranded["status"] == "in_progress"

    resumed = client.post(f"/interview/{interview_id}/continue").json()
    assert resumed["current_question"] is not None
    assert resumed["status"] == "in_progress"


def test_continue_409s_on_a_completed_interview(client: TestClient, monkeypatch) -> None:
    _use_client(monkeypatch, _FakeInterviewClient())
    notebook_id = _notebook_with_material(client)
    interview_id = client.post(f"/notebooks/{notebook_id}/interview/start").json()["id"]
    client.post(f"/interview/{interview_id}/end")

    assert client.post(f"/interview/{interview_id}/continue").status_code == 409


# ---------------------------------------------------------------------------
# Reading back, and cleanup
# ---------------------------------------------------------------------------


def test_get_latest_returns_the_most_recent_interview(client: TestClient, monkeypatch) -> None:
    _use_client(monkeypatch, _FakeInterviewClient())
    notebook_id = _notebook_with_material(client)
    first_id = client.post(f"/notebooks/{notebook_id}/interview/start").json()["id"]
    client.post(f"/interview/{first_id}/end")
    second_id = client.post(f"/notebooks/{notebook_id}/interview/start").json()["id"]

    latest = client.get(f"/notebooks/{notebook_id}/interview").json()
    assert latest["id"] == second_id


def test_get_session_by_id_returns_every_turn(client: TestClient, monkeypatch) -> None:
    _use_client(monkeypatch, _FakeInterviewClient())
    monkeypatch.setattr("app.services.interview.score_answer", _fixed_scorer(75))
    notebook_id = _notebook_with_material(client)
    interview_id = client.post(f"/notebooks/{notebook_id}/interview/start").json()["id"]
    client.post(f"/interview/{interview_id}/answer", json={"answer": ANSWER_TEXT})

    body = client.get(f"/interview/{interview_id}").json()
    assert len(body["turns"]) == 2
    assert [turn["question_index"] for turn in body["turns"]] == [0, 1]


def test_timestamps_are_utc_marked(client: TestClient, monkeypatch) -> None:
    """Same naive-datetime trap TimestampedModel documents: an unmarked
    timestamp gets parsed as local time by the browser and shifts every
    "x minutes ago" by the viewer's offset."""
    _use_client(monkeypatch, _FakeInterviewClient())
    notebook_id = _notebook_with_material(client)
    body = client.post(f"/notebooks/{notebook_id}/interview/start").json()

    assert body["created_at"].endswith("Z")
    assert body["current_question"]["asked_at"].endswith("Z")


@pytest.mark.asyncio
async def test_deleting_a_notebook_removes_its_interviews(
    client: TestClient, monkeypatch
) -> None:
    _use_client(monkeypatch, _FakeInterviewClient())
    monkeypatch.setattr("app.services.interview.score_answer", _fixed_scorer(70))
    notebook_id = _notebook_with_material(client)
    interview_id = client.post(f"/notebooks/{notebook_id}/interview/start").json()["id"]
    client.post(f"/interview/{interview_id}/answer", json={"answer": ANSWER_TEXT})

    assert client.delete(f"/notebooks/{notebook_id}").status_code in (200, 204)

    async with client.test_session_factory() as db:
        sessions = await db.execute(
            select(InterviewSession).where(InterviewSession.notebook_id == notebook_id)
        )
        assert sessions.scalars().all() == []
        turns = await db.execute(
            select(InterviewQA).where(InterviewQA.session_id == interview_id)
        )
        assert turns.scalars().all() == []


# ---------------------------------------------------------------------------
# Scoring model transparency
# ---------------------------------------------------------------------------


def test_scoring_metrics_endpoint_reports_held_out_performance(client: TestClient) -> None:
    body = client.get("/interview/meta/scoring").json()
    assert body["using_fallback"] is False
    assert body["model"] == "GradientBoostingRegressor"
    assert body["held_out_mae"] is not None
    assert body["held_out_r2"] is not None


def test_scoring_metrics_endpoint_says_so_when_falling_back(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr("app.services.answer_scoring.METRICS_PATH", Path("/nonexistent/metrics.json"))
    body = client.get("/interview/meta/scoring").json()
    assert body["using_fallback"] is True
    assert body["held_out_mae"] is None
