from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import settings
from app.migrations import run_schema_migrations
from app.routers import chat, documents, interview, notebooks, presentation, quiz
from app.services.processing_pipeline import reconcile_interrupted_documents


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Alembic owns the schema, which is what lets the same code run on
    # SQLite locally and Postgres when deployed. An existing pre-Alembic
    # database is adopted rather than rebuilt - see app/migrations.py.
    await run_schema_migrations()
    # Accessed via the `db` module (not `from app.db import async_session_factory`)
    # so tests that monkeypatch `db.async_session_factory` to a test engine are
    # respected here too — a plain `from`-import would capture the production
    # value at import time and ignore the patch.
    async with db.async_session_factory() as session:
        await reconcile_interrupted_documents(session)
    yield


app = FastAPI(title="StudyMind API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(notebooks.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(quiz.router)
app.include_router(presentation.router)
app.include_router(interview.notebook_router)
app.include_router(interview.session_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
