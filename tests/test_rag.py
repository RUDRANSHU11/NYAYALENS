"""Retrieval and the in-memory document store, including its privacy guarantees
(TTL expiry, unguessable ids, hard cap on how much is kept)."""

import time

from backend import config
from backend.document_processing.chunking import Chunk
from backend.rag import embeddings, store


def sample_chunks() -> list[Chunk]:
    return [
        Chunk(id="c0", text="Either party may terminate this Agreement on 30 days written notice.", clause="4"),
        Chunk(id="c1", text="The Company shall pay a gross salary of Rs. 9,00,000 per annum.", clause="2"),
        Chunk(id="c2", text="The Employee shall not disclose confidential information.", clause="6"),
    ]


def test_embeddings_are_normalised():
    vectors = embeddings.embed_documents(["notice period", "salary payment"])
    assert vectors.shape[0] == 2
    assert all(abs(float((vector**2).sum()) - 1.0) < 1e-5 for vector in vectors)


def test_retrieval_finds_the_relevant_clause():
    document = store.add("contract.txt", 0, sample_chunks())
    results = store.search(document, "how much notice do I have to give?", top_k=1)
    assert results[0][0].id == "c0"


def test_retrieval_returns_at_most_top_k():
    document = store.add("contract.txt", 0, sample_chunks())
    assert len(store.search(document, "salary", top_k=2)) == 2


def test_documents_have_unguessable_ids():
    first = store.add("a.txt", 0, sample_chunks())
    second = store.add("b.txt", 0, sample_chunks())
    assert first.id != second.id
    assert len(first.id) >= 20


def test_document_expires_after_its_ttl(monkeypatch):
    document = store.add("contract.txt", 0, sample_chunks())
    monkeypatch.setattr(config, "DOC_TTL_SECONDS", 0)
    time.sleep(0.01)
    assert store.get(document.id) is None


def test_delete_removes_the_document():
    document = store.add("contract.txt", 0, sample_chunks())
    assert store.delete(document.id) is True
    assert store.get(document.id) is None
    assert store.delete(document.id) is False


def test_store_is_capped(monkeypatch):
    monkeypatch.setattr(config, "MAX_DOCS", 2)
    first = store.add("a.txt", 0, sample_chunks())
    store.add("b.txt", 0, sample_chunks())
    newest = store.add("c.txt", 0, sample_chunks())

    assert store.get(first.id) is None  # oldest evicted
    assert store.get(newest.id) is not None
    assert store.count() == 2


def test_chunk_lookup_by_id():
    document = store.add("contract.txt", 0, sample_chunks())
    assert document.chunk("c2").clause == "6"
    assert document.chunk("nope") is None
