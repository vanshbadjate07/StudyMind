import json
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.models import (
    ChatMessage,
    ChatRole,
    DocumentStatus,
    GoalType,
    InterviewMode,
    InterviewQA,
    InterviewSession,
    InterviewStatus,
    Overview,
    OverviewStatus,
    Presentation,
    PresentationStatus,
    Quiz,
    QuizStatus,
)


class TimestampedModel(BaseModel):
    """SQLite has no real timezone-aware storage, so SQLAlchemy always hands
    back naive datetimes here — they're UTC in fact (server_default=func.now()
    / datetime.now(UTC) at insert time) but carry no marker saying so. Left
    alone, that serializes as e.g. "2026-08-17T10:07:22" with no offset, and
    the browser's `new Date(...)` parses a marker-less string as *local*
    time — silently shifting every timestamp by the viewer's UTC offset (this
    is exactly why timestamps were showing "5 hours ago" for things created
    seconds earlier, at IST/UTC+5:30). Stamping UTC before serializing makes
    every timestamp this API returns an unambiguous ISO 8601 string."""

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("created_at", "updated_at", check_fields=False)
    def _serialize_utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class DocumentRead(TimestampedModel):
    id: str
    notebook_id: str
    filename: str
    status: DocumentStatus
    page_count: int | None
    char_count: int | None
    chunk_count: int | None
    error_reason: str | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime


class DocumentList(BaseModel):
    documents: list[DocumentRead]


class NotebookRead(TimestampedModel):
    id: str
    name: str
    goal_type: GoalType | None
    goal_description: str | None
    created_at: datetime
    updated_at: datetime


class NotebookList(BaseModel):
    notebooks: list[NotebookRead]


class NotebookCreate(BaseModel):
    name: str | None = None


class NotebookUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class GoalUpdate(BaseModel):
    goal_type: GoalType
    goal_description: str | None = None


class TopicSummary(BaseModel):
    title: str
    summary: str
    key_concepts: list[str]


class OverviewResult(BaseModel):
    """Validates the LLM's final synthesis output. A degenerate response (no
    topics, or a nonsensical time estimate) fails validation and is treated
    as an invalid LLM response — not a "successful" empty overview."""

    short_summary: str = Field(min_length=1)
    topics: list[TopicSummary] = Field(min_length=1)
    estimated_minutes: int = Field(gt=0)


class SectionSummary(BaseModel):
    """Validates the LLM's per-section map-stage output."""

    summary: str


class TitleSuggestion(BaseModel):
    """Validates the LLM's notebook auto-titling output."""

    title: str = Field(min_length=1, max_length=80)


class OverviewRead(TimestampedModel):
    id: str
    notebook_id: str
    status: OverviewStatus
    short_summary: str | None
    topics: list[TopicSummary]
    estimated_minutes: int | None
    error_reason: str | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, overview: Overview) -> "OverviewRead":
        raw_topics = json.loads(overview.topics_json) if overview.topics_json else []
        return cls(
            id=overview.id,
            notebook_id=overview.notebook_id,
            status=overview.status,
            short_summary=overview.short_summary,
            topics=[TopicSummary(**topic) for topic in raw_topics],
            estimated_minutes=overview.estimated_minutes,
            error_reason=overview.error_reason,
            error_detail=overview.error_detail,
            created_at=overview.created_at,
            updated_at=overview.updated_at,
        )


class QuizDifficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    MIXED = "mixed"


class QuizGenerateRequest(BaseModel):
    question_count: int = Field(default=8, ge=3, le=20)
    difficulty: QuizDifficulty = QuizDifficulty.MIXED
    # Off by default: matches the PRD's "answerable directly from the
    # material" baseline. On is an explicit opt-in to let the model round
    # out thin material with its own general knowledge, the same "off by
    # default, explicit toggle" pattern as chat's internet mode.
    allow_general_knowledge: bool = False
    focus: str | None = Field(default=None, max_length=200)

    @field_validator("focus")
    @classmethod
    def _blank_focus_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class QuizQuestionResult(BaseModel):
    """Validates one question from the LLM's quiz-generation output."""

    question: str = Field(min_length=1)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=1)


class QuizGenerationResult(BaseModel):
    questions: list[QuizQuestionResult] = Field(min_length=1)


class QuizQuestionRead(BaseModel):
    question: str
    options: list[str]
    correct_index: int
    explanation: str


class QuizRead(TimestampedModel):
    id: str
    notebook_id: str
    status: QuizStatus
    questions: list[QuizQuestionRead]
    error_reason: str | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, quiz: Quiz) -> "QuizRead":
        raw_questions = json.loads(quiz.questions_json) if quiz.questions_json else []
        return cls(
            id=quiz.id,
            notebook_id=quiz.notebook_id,
            status=quiz.status,
            questions=[QuizQuestionRead(**q) for q in raw_questions],
            error_reason=quiz.error_reason,
            error_detail=quiz.error_detail,
            created_at=quiz.created_at,
            updated_at=quiz.updated_at,
        )


class PresentationStyle(str, Enum):
    CONCISE = "concise"
    EXAM_FOCUSED = "exam_focused"
    VISUAL_HEAVY = "visual_heavy"


class PresentationGenerateRequest(BaseModel):
    slide_count: int = Field(default=10, ge=5, le=30)
    style: PresentationStyle = PresentationStyle.CONCISE
    focus: str | None = Field(default=None, max_length=200)

    @field_validator("focus")
    @classmethod
    def _blank_focus_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class SlideLayout(str, Enum):
    TITLE = "title"
    BULLETS = "bullets"
    TWO_COLUMN = "two_column"
    QUOTE = "quote"
    COMPARISON = "comparison"
    DIAGRAM = "diagram"


class SlideColumn(BaseModel):
    heading: str = Field(min_length=1, max_length=80)
    lines: list[str] = Field(min_length=1, max_length=6)


class DiagramNode(BaseModel):
    label: str = Field(min_length=1, max_length=40)


class DiagramEdge(BaseModel):
    """A connection drawn from one node to another, by index into the
    slide's `nodes` list. The LLM describes structure only (which node
    connects to which, with what label) — never raw drawing coordinates or
    markup — so the diagram is always laid out and drawn deterministically
    in code, never by trusting model-generated graphics."""

    from_index: int = Field(ge=0)
    to_index: int = Field(ge=0)
    label: str | None = Field(default=None, max_length=30)


class SlideResult(BaseModel):
    """One slide from the LLM's generation output. Which fields matter
    depends on `layout` — the renderer reads only the fields relevant to
    that layout and ignores the rest, so the schema stays one flat shape
    rather than a discriminated union the model would be more likely to get
    wrong."""

    layout: SlideLayout
    # No min_length: a real cloud model, told "title isn't shown for quote
    # layout" in the prompt, reasonably sent an empty string for one rather
    # than a placeholder — observed live against Groq's gpt-oss-120b, not a
    # hypothetical. Rejecting that at the schema level failed the entire
    # deck over one cosmetic field; emptiness for non-quote layouts (which
    # do need a real heading) is instead caught by
    # presentation_generation._is_renderable_slide, which drops just that
    # slide rather than the whole batch.
    title: str = Field(default="", max_length=120)
    subtitle: str | None = Field(default=None, max_length=200)  # TITLE
    lines: list[str] = Field(default_factory=list, max_length=8)  # BULLETS
    columns: list[SlideColumn] = Field(default_factory=list, max_length=2)  # TWO_COLUMN / COMPARISON
    quote: str | None = Field(default=None, max_length=400)  # QUOTE
    nodes: list[DiagramNode] = Field(default_factory=list, max_length=6)  # DIAGRAM
    edges: list[DiagramEdge] = Field(default_factory=list, max_length=10)  # DIAGRAM
    caption: str | None = Field(default=None, max_length=150)  # DIAGRAM
    attribution: str | None = Field(default=None, max_length=100)  # QUOTE


class PresentationGenerationResult(BaseModel):
    slides: list[SlideResult] = Field(min_length=1)


class PresentationRead(TimestampedModel):
    id: str
    notebook_id: str
    status: PresentationStatus
    slide_count: int | None
    style: str | None
    focus: str | None
    error_reason: str | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, presentation: Presentation) -> "PresentationRead":
        return cls(
            id=presentation.id,
            notebook_id=presentation.notebook_id,
            status=presentation.status,
            slide_count=presentation.slide_count,
            style=presentation.style,
            focus=presentation.focus,
            error_reason=presentation.error_reason,
            error_detail=presentation.error_detail,
            created_at=presentation.created_at,
            updated_at=presentation.updated_at,
        )


class ChatCitation(BaseModel):
    document_id: str
    filename: str
    page_number: int | None


class ChatAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    internet_mode: bool = False


class ChatMessageRead(TimestampedModel):
    id: str
    role: ChatRole
    content: str
    citations: list[ChatCitation]
    grounded: bool
    used_internet: bool
    created_at: datetime

    @classmethod
    def from_model(cls, message: ChatMessage) -> "ChatMessageRead":
        raw_citations = json.loads(message.citations_json) if message.citations_json else []
        return cls(
            id=message.id,
            role=message.role,
            content=message.content,
            citations=[ChatCitation(**citation) for citation in raw_citations],
            grounded=message.grounded,
            used_internet=message.used_internet,
            created_at=message.created_at,
        )


class ChatMessageList(BaseModel):
    messages: list[ChatMessageRead]


# ---------------------------------------------------------------------------
# Mock interview (PRD 6.7-6.8)
# ---------------------------------------------------------------------------


class InterviewStartRequest(BaseModel):
    mode: InterviewMode = InterviewMode.TEXT
    question_limit: int = Field(default=8, ge=3, le=20)
    # Optional steer, same shape as quiz/presentation's focus.
    focus: str | None = Field(default=None, max_length=200)

    @field_validator("focus")
    @classmethod
    def _blank_focus_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class InterviewAnswerRequest(BaseModel):
    # No min_length: an empty answer is a real, scoreable event (the user
    # skipping a question), not invalid input. The scorer treats it as a
    # non-answer and scores it zero, which is information the final report
    # should carry rather than a 422 the user has to work around.
    answer: str = Field(default="", max_length=5000)


class InterviewQuestionResult(BaseModel):
    """Validates the LLM's per-question generation output. `key_concepts` is
    bounded on both sides: with none, concept coverage has nothing to measure
    and the score collapses onto similarity alone; with too many, a correct
    answer gets marked down for omitting trivia."""

    question: str = Field(min_length=1, max_length=500)
    ideal_answer: str = Field(min_length=1, max_length=2000)
    key_concepts: list[str] = Field(min_length=2, max_length=6)


class InterviewTopicsResult(BaseModel):
    """Validates the fallback topic-agenda generation, used only when the
    notebook has no ready overview to take topics from."""

    topics: list[str] = Field(min_length=1, max_length=12)


class InterviewQARead(BaseModel):
    id: str
    question_index: int
    topic: str | None
    question: str
    is_probe: bool
    answer_text: str | None
    score: int | None
    feedback: str | None
    missed_points: list[str]
    features: dict[str, float]
    # Withheld until the user has answered: showing the model answer next to
    # an unanswered question would just be the answer key.
    ideal_answer: str | None
    key_concepts: list[str]
    asked_at: datetime
    answered_at: datetime | None

    @field_serializer("asked_at", "answered_at")
    def _serialize_utc(self, value: datetime | None) -> str | None:
        # Same naive-datetime-is-really-UTC problem TimestampedModel solves;
        # this model has its own timestamp column names, so it needs its own
        # serializer rather than inheriting that one.
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @classmethod
    def from_model(cls, qa: InterviewQA) -> "InterviewQARead":
        answered = qa.answered_at is not None
        return cls(
            id=qa.id,
            question_index=qa.question_index,
            topic=qa.topic,
            question=qa.question,
            is_probe=qa.is_probe,
            answer_text=qa.answer_text,
            score=qa.score,
            feedback=qa.feedback,
            missed_points=json.loads(qa.missed_points_json) if qa.missed_points_json else [],
            features=json.loads(qa.features_json) if qa.features_json else {},
            ideal_answer=qa.ideal_answer if answered else None,
            key_concepts=json.loads(qa.key_concepts_json) if qa.key_concepts_json else [],
            asked_at=qa.asked_at,
            answered_at=qa.answered_at,
        )


class InterviewSessionRead(TimestampedModel):
    id: str
    notebook_id: str
    mode: InterviewMode
    status: InterviewStatus
    question_limit: int
    overall_score: int | None
    weak_areas: list[str]
    topics: list[str]
    turns: list[InterviewQARead]
    # The turn awaiting an answer, if any. Pulled out of `turns` as a
    # convenience so the UI doesn't have to scan for "the one with no
    # answered_at" on every render.
    current_question: InterviewQARead | None
    answered_count: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    @field_serializer("completed_at")
    def _serialize_completed_at(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @classmethod
    def from_model(cls, session: InterviewSession, qa_items: list[InterviewQA]) -> "InterviewSessionRead":
        turns = [InterviewQARead.from_model(qa) for qa in qa_items]
        pending = next((turn for turn in turns if turn.answered_at is None), None)
        return cls(
            id=session.id,
            notebook_id=session.notebook_id,
            mode=session.mode,
            status=session.status,
            question_limit=session.question_limit,
            overall_score=session.overall_score,
            weak_areas=json.loads(session.weak_areas_json) if session.weak_areas_json else [],
            topics=json.loads(session.topics_json) if session.topics_json else [],
            turns=turns,
            current_question=pending,
            answered_count=sum(1 for turn in turns if turn.answered_at is not None),
            created_at=session.created_at,
            updated_at=session.updated_at,
            completed_at=session.completed_at,
        )


class AnswerScoringMetrics(BaseModel):
    """The scoring model's held-out metrics, surfaced through the API so the
    UI can show how the scorer performs rather than asking the user to take
    its numbers on trust."""

    held_out_mae: float | None = None
    held_out_r2: float | None = None
    model: str | None = None
    corpus_size: int | None = None
    using_fallback: bool = False


class TranscriptionRead(BaseModel):
    """A spoken answer turned into text. Returned for the user to read and
    correct BEFORE it is scored, rather than scored directly from audio:
    a mis-transcription the user never saw would cost them a question and
    look like the scorer being wrong."""

    text: str
    backend: str


class VoiceCapability(BaseModel):
    """Whether voice answers can be transcribed here, and by what. Lets the
    UI hide voice mode when it cannot work, and warn about a slow first run
    when transcribing locally, instead of failing at the moment of use."""

    available: bool
    backend: str
    detail: str | None = None
