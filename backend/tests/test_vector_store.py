import uuid

import pytest

from app.services.embeddings import embed_texts
from app.services.vector_store import VectorStore


@pytest.fixture
def store(tmp_path) -> VectorStore:
    return VectorStore(persist_dir=tmp_path, collection_name="test_collection")


def test_query_returns_the_most_similar_chunk_first(store: VectorStore) -> None:
    document_id = str(uuid.uuid4())
    texts = [
        "Photosynthesis converts sunlight into chemical energy in plants.",
        "The stock market fluctuates based on supply and demand.",
        "Mitochondria are the powerhouse of the cell.",
    ]
    chunk_ids = [str(uuid.uuid4()) for _ in texts]
    embeddings = embed_texts(texts)

    store.add(
        document_id=document_id,
        chunk_ids=chunk_ids,
        texts=texts,
        embeddings=embeddings,
        page_numbers=[1, 2, 3],
    )

    results = store.query("How do plants create energy from light?", top_k=1)

    assert len(results) == 1
    assert results[0].text == texts[0]
    assert results[0].document_id == document_id
    assert results[0].page_number == 1


def test_delete_document_removes_all_its_vectors(store: VectorStore) -> None:
    document_id = str(uuid.uuid4())
    texts = ["A fact about geology.", "A fact about chemistry."]
    chunk_ids = [str(uuid.uuid4()) for _ in texts]
    embeddings = embed_texts(texts)

    store.add(
        document_id=document_id,
        chunk_ids=chunk_ids,
        texts=texts,
        embeddings=embeddings,
        page_numbers=[1, 1],
    )
    assert store.count_for_document(document_id) == 2

    store.delete_document(document_id)

    assert store.count_for_document(document_id) == 0


def test_query_is_scoped_to_document_id_when_provided(store: VectorStore) -> None:
    doc_a, doc_b = str(uuid.uuid4()), str(uuid.uuid4())
    texts_a = ["Content unique to document A about volcanoes."]
    texts_b = ["Content unique to document B about volcanoes."]

    store.add(doc_a, [str(uuid.uuid4())], texts_a, embed_texts(texts_a), [1])
    store.add(doc_b, [str(uuid.uuid4())], texts_b, embed_texts(texts_b), [1])

    results = store.query("volcanoes", top_k=5, document_id=doc_a)

    assert len(results) == 1
    assert results[0].document_id == doc_a
