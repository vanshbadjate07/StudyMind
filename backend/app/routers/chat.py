from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import ChatMessage, Notebook
from app.schemas import ChatAskRequest, ChatMessageList, ChatMessageRead
from app.services.chat import ask_question
from app.services.ollama_client import OllamaTimeoutError, OllamaUnreachableError

router = APIRouter(prefix="/notebooks/{notebook_id}/chat", tags=["chat"])


@router.get("/messages", response_model=ChatMessageList)
async def list_chat_messages(
    notebook_id: str, session: AsyncSession = Depends(get_session)
) -> ChatMessageList:
    notebook = await session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found.")

    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.notebook_id == notebook_id)
        .order_by(ChatMessage.created_at, ChatMessage.id)
    )
    messages = [ChatMessageRead.from_model(m) for m in result.scalars().all()]
    return ChatMessageList(messages=messages)


@router.post("/messages", response_model=ChatMessageRead, status_code=status.HTTP_201_CREATED)
async def ask_chat_question(
    notebook_id: str, body: ChatAskRequest, session: AsyncSession = Depends(get_session)
) -> ChatMessageRead:
    notebook = await session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found.")

    try:
        assistant_message = await ask_question(
            notebook, body.question, body.internet_mode, session
        )
    except (OllamaUnreachableError, OllamaTimeoutError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Couldn't reach the AI service — your question was saved, please try again.",
        ) from exc

    return ChatMessageRead.from_model(assistant_message)
