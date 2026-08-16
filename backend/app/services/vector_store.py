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
        self, text: str, top_k: int = 5, document_id: str | None = None
    ) -> list[VectorSearchResult]:
        query_embedding = embed_texts([text])[0]
        where = {"document_id": document_id} if document_id else None
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
