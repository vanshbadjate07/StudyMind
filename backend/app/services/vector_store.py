import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import chromadb

from app.config import settings
from app.services.embeddings import embed_texts

# chromadb 0.5.x's telemetry client is incompatible with newer posthog releases
# (a TypeError on every event) even with anonymized_telemetry=False. The error is
# caught internally and harmless, but floods the logs on every operation.
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)


@dataclass(frozen=True)
class VectorSearchResult:
    chunk_id: str
    text: str
    document_id: str
    page_number: int | None
    distance: float


class VectorStore:
    def __init__(self, persist_dir: Path | None = None, collection_name: str | None = None) -> None:
        self._client = chromadb.PersistentClient(
            path=str(persist_dir or settings.chroma_dir),
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=collection_name or settings.chroma_collection_name
        )

    def add(
        self,
        document_id: str,
        chunk_ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        page_numbers: list[int | None],
    ) -> None:
        if not chunk_ids:
            return
        metadatas = [
            {"document_id": document_id, **({"page_number": p} if p is not None else {})}
            for p in page_numbers
        ]
        self._collection.add(ids=chunk_ids, embeddings=embeddings, documents=texts, metadatas=metadatas)

    def query(
        self,
        text: str,
        top_k: int = 5,
        document_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> list[VectorSearchResult]:
        """`document_ids` scopes the search to any of several documents (e.g.
        every ready document in a notebook, for notebook-wide chat) —
        `document_id` remains for the single-document case. An explicitly
        empty `document_ids` list (a notebook with no ready documents) short-
        circuits to no results rather than querying Chroma with an empty
        `$in`, which it doesn't accept."""
        if document_ids is not None and not document_ids:
            return []

        if document_ids:
            where = {"document_id": {"$in": document_ids}}
        elif document_id:
            where = {"document_id": document_id}
        else:
            where = None

        query_embedding = embed_texts([text])[0]
        results = self._collection.query(
            query_embeddings=[query_embedding], n_results=top_k, where=where
        )

        ids = results["ids"][0]
        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]

        return [
            VectorSearchResult(
                chunk_id=ids[i],
                text=documents[i],
                document_id=metadatas[i]["document_id"],
                page_number=metadatas[i].get("page_number"),
                distance=distances[i],
            )
            for i in range(len(ids))
        ]

    def delete_document(self, document_id: str) -> None:
        self._collection.delete(where={"document_id": document_id})

    def count_for_document(self, document_id: str) -> int:
        result = self._collection.get(where={"document_id": document_id})
        return len(result["ids"])


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStore:
    return VectorStore()
