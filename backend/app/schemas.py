import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import ChatMessage, ChatRole, DocumentStatus, GoalType, Overview, OverviewStatus


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class NotebookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class OverviewRead(BaseModel):
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


class ChatMessageRead(BaseModel):
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
