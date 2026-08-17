import json
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.models import ChatMessage, ChatRole, DocumentStatus, GoalType, Overview, OverviewStatus


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
