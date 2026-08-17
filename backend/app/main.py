from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import settings
from app.migrations import (
    migrate_documents_notebook_column,
    migrate_overview_short_summary_column,
    migrate_overview_to_notebook_scope,
)
from app.routers import documents, notebooks
from app.services.processing_pipeline import reconcile_interrupted_documents


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await db.init_db()
    await migrate_documents_notebook_column()
    await migrate_overview_to_notebook_scope()
    await migrate_overview_short_summary_column()
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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
