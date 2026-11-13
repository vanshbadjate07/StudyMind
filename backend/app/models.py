import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ChatRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class OverviewStatus(str, enum.Enum):
    PENDING = "pending"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class QuizStatus(str, enum.Enum):
    PENDING = "pending"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class PresentationStatus(str, enum.Enum):
    PENDING = "pending"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class InterviewMode(str, enum.Enum):
    TEXT = "text"
    VOICE = "voice"


class InterviewStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class GoalType(str, enum.Enum):
    EXAM = "exam"
    INTERVIEW = "interview"
    SKILL = "skill"
    EXPLORATION = "exploration"
    CUSTOM = "custom"


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


def _uuid() -> str:
    return str(uuid.uuid4())


class Notebook(Base):
    __tablename__ = "notebooks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Untitled")
    goal_type: Mapped[GoalType | None] = mapped_column(
        Enum(GoalType, values_callable=_enum_values), nullable=True
    )
    goal_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="notebook", cascade="all, delete-orphan"
    )
    chat_messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="notebook", cascade="all, delete-orphan"
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    notebook_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, values_callable=_enum_values),
        nullable=False,
        default=DocumentStatus.PENDING,
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    notebook: Mapped["Notebook"] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    """One turn of a notebook's chat history — grounded conversational Q&A
    over the notebook's documents (PRD 6.4). Scoped to the notebook, not a
    single document, matching the rest of the notebook-as-unit-of-study
    architecture."""

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    notebook_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[ChatRole] = mapped_column(Enum(ChatRole, values_callable=_enum_values), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON-encoded list of {document_id, filename, page_number} — the sources
    # an assistant answer was grounded in. Empty/null for user messages and
    # for assistant answers that weren't grounded in any retrieved material.
    citations_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Whether this answer was actually grounded in retrieved material (as
    # opposed to a "not covered in your material" refusal, or an
    # internet-mode answer drawn from the model's general knowledge).
    # Always False for user messages.
    grounded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Whether this answer drew on the model's general knowledge beyond the
    # retrieved material (only possible when internet mode was on for the
    # question that produced it). Always False for user messages.
    used_internet: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Python-side default (not server_default=func.now(), which via SQLite's
    # CURRENT_TIMESTAMP only has second resolution) — a single chat turn
    # writes two rows (user then assistant) and history is always sorted by
    # this column, so sub-second precision is what keeps rapid successive
    # messages in correct order rather than relying on SQLite's insertion
    # order as an undocumented tiebreak.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    notebook: Mapped["Notebook"] = relationship(back_populates="chat_messages")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="chunks")


class Overview(Base):
    """One combined overview per notebook, synthesized across every ready
    document it contains — not one overview per document. A notebook is the
    unit of study (e.g. "Learning Python" made of several PDFs), so this
    mirrors how Google NotebookLM treats a notebook's sources as a single
    body of material."""

    __tablename__ = "overviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    notebook_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("notebooks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[OverviewStatus] = mapped_column(
        Enum(OverviewStatus, values_callable=_enum_values),
        nullable=False,
        default=OverviewStatus.PENDING,
    )
    # A short, plain-prose "what is this about" (2-3 sentences, no bullet
    # points) — this is what's shown by default; topics_json below is the
    # detailed breakdown, tucked behind a UI toggle.
    short_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON-encoded list of {title, summary, key_concepts: [str]} — read/written as a
    # whole, never queried piecemeal, so a structured column set would be overkill.
    topics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Quiz(Base):
    """One quiz per notebook, generated on demand (unlike Overview, which
    generates automatically) from every ready document it contains. Not
    auto-regenerated when documents change — the user re-triggers it
    explicitly, since a quiz mid-attempt silently changing under them would
    be worse than a stale one."""

    __tablename__ = "quizzes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    notebook_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("notebooks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[QuizStatus] = mapped_column(
        Enum(QuizStatus, values_callable=_enum_values),
        nullable=False,
        default=QuizStatus.PENDING,
    )
    # JSON-encoded list of {question, options: [4 strings], correct_index,
    # explanation} — read/written as a whole, never queried piecemeal, same
    # reasoning as Overview.topics_json.
    questions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Presentation(Base):
    """One presentation per notebook, generated on demand from every ready
    document it contains — same regeneration model as Quiz (user-triggered,
    not auto-regenerated when documents change), not Overview. Unlike
    Quiz/Overview, the generated result is a file on disk rather than JSON in
    this row — file_path points at it, mirroring how Document.file_path
    points at an uploaded source file."""

    __tablename__ = "presentations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    notebook_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("notebooks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[PresentationStatus] = mapped_column(
        Enum(PresentationStatus, values_callable=_enum_values),
        nullable=False,
        default=PresentationStatus.PENDING,
    )
    slide_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    style: Mapped[str | None] = mapped_column(String(32), nullable=True)
    focus: Mapped[str | None] = mapped_column(String(200), nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InterviewSession(Base):
    """One mock interview run over a notebook's material (PRD 6.7-6.8).

    Unlike Overview/Quiz/Presentation, this is NOT one row per notebook: an
    interview is an event you do repeatedly, and past runs are the record of
    whether you improved, so they're kept rather than overwritten.

    Also unlike those three, generation is synchronous rather than a
    background task with a status row. The user is sitting there waiting for
    the next question, so a request/response turn is the honest shape -
    there's no artefact being built in the background to poll for. `status`
    here tracks how far through the interview the user is, not whether a
    generation job finished.
    """

    __tablename__ = "interview_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    notebook_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mode: Mapped[InterviewMode] = mapped_column(
        Enum(InterviewMode, values_callable=_enum_values), nullable=False, default=InterviewMode.TEXT
    )
    status: Mapped[InterviewStatus] = mapped_column(
        Enum(InterviewStatus, values_callable=_enum_values),
        nullable=False,
        default=InterviewStatus.IN_PROGRESS,
    )
    # How many questions this run will ask at most. Stored per session, not
    # read from settings at report time, so changing the default later can't
    # retroactively alter how a finished interview reads.
    question_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # JSON-encoded list of topic strings the agent flagged as weak, written
    # once when the interview completes. Read and written as a whole, same
    # reasoning as Overview.topics_json.
    weak_areas_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The topic list this run works through, resolved once at start (from the
    # notebook's overview, or generated) and frozen. Re-resolving per turn
    # would let the agenda shift mid-interview if a document finished
    # processing partway through.
    topics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Python-side default rather than server_default=func.now(): SQLite's
    # CURRENT_TIMESTAMP only has second resolution, and "the notebook's latest
    # interview" is resolved by ordering on this column. Starting a second
    # interview within the same second as the first tied the sort, leaving the
    # tiebreak to a random UUID - so the wrong session came back as "latest".
    # Same problem, and same fix, as ChatMessage.created_at.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    qa_items: Mapped[list["InterviewQA"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="InterviewQA.question_index"
    )


class InterviewQA(Base):
    """One question-and-answer turn of an interview.

    `answer_text` holds the transcript when the answer arrived as speech
    (6.8), so text and voice share one table and one scoring path - a
    separate voice table would mean a second evaluation path that could
    silently drift from the text one.

    The scorer's feature breakdown is persisted alongside the score
    (`features_json`), not recomputed on read: the embedding model and the
    trained artefact can both change between runs, and a past interview's
    report should keep saying what it said at the time.
    """

    __tablename__ = "interview_qa"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Which topic from the session's agenda this question probes. Nullable
    # because a generated agenda can be empty for very thin material, in
    # which case questions are asked against the notebook as a whole.
    topic: Mapped[str | None] = mapped_column(String(200), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # The answer drawn from the user's own material, generated with the
    # question. This is what the user's answer is scored against, and it's
    # shown back to them after they answer as the model answer.
    ideal_answer: Mapped[str] = mapped_column(Text, nullable=False)
    key_concepts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # True when this question re-probes a topic the previous answer scored
    # poorly on, rather than moving to new ground. Persisted so the report
    # can show the agent's adaptation rather than asserting it happened.
    is_probe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    missed_points_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    features_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    asked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped["InterviewSession"] = relationship(back_populates="qa_items")
