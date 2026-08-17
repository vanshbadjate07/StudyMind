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
