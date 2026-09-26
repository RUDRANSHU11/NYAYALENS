"""The store has two interchangeable backends.

The Redis one is what makes the API horizontally scalable: these tests point two
backends at one fake server, which is exactly the shape of two app instances
sharing one Redis.
"""

import time

import pytest

from backend import config
from backend.document_processing.chunking import Chunk
from backend.rag import store
from tests.fake_redis import FakeRedis


def sample_chunks() -> list[Chunk]:
    return [
        Chunk(id="c0", text="Either party may terminate on 30 days written notice.", clause="4"),
        Chunk(id="c1", text="The Company shall pay a salary of Rs. 9,00,000 per annum.", clause="2"),
        Chunk(id="c2", text="The Employee shall not disclose confidential information.", clause="6"),
    ]


@pytest.fixture
def shared_redis():
    """Two backends over one server - instance A and instance B."""
    server = FakeRedis()
    instance_a, instance_b = store.RedisBackend(server), store.RedisBackend(server)
    store.use_backend(instance_a)
    yield instance_a, instance_b
    store.use_backend(store.MemoryBackend())


def test_a_document_uploaded_on_one_instance_is_readable_on_another(shared_redis):
    _instance_a, instance_b = shared_redis
    document = store.add("contract.txt", 2, sample_chunks(), flags={"c0": ["Termination"]})

    served_elsewhere = instance_b.fetch(document.id)

    assert served_elsewhere is not None
    assert served_elsewhere.name == "contract.txt"
    assert served_elsewhere.pages == 2
    assert served_elsewhere.flags == {"c0": ["Termination"]}
    assert [chunk.id for chunk in served_elsewhere.chunks] == ["c0", "c1", "c2"]
    assert served_elsewhere.chunk("c2").clause == "6"


def test_retrieval_works_on_the_instance_that_did_not_embed(shared_redis):
    _instance_a, instance_b = shared_redis
    document = store.add("contract.txt", 0, sample_chunks())

    hit, score = store.search(instance_b.fetch(document.id), "how much notice?", top_k=1)[0]

    assert hit.id == "c0"  # vectors survived the round trip, index rebuilt on read
    assert 0.0 < score <= 1.0


def test_caches_and_deletes_are_shared(shared_redis):
    _instance_a, instance_b = shared_redis
    document = store.add("contract.txt", 0, sample_chunks())

    store.remember(document.id, "answer", "notice?|en", {"answer": "Thirty days."})
    assert instance_b.cached(document.id, "answer", "notice?|en") == {"answer": "Thirty days."}

    instance_b.drop(document.id)
    assert store.get(document.id) is None  # deleted everywhere, not just on B
    assert instance_b.cached(document.id, "answer", "notice?|en") is None


def test_redis_documents_carry_the_same_ttl(shared_redis):
    instance_a, _instance_b = shared_redis
    document = store.add("contract.txt", 0, sample_chunks())

    assert instance_a._client.expiries[f"{store.PREFIX}:doc:{document.id}"] == (
        config.DOC_TTL_SECONDS
    )


def test_rate_limit_counters_are_shared(shared_redis):
    instance_a, instance_b = shared_redis

    assert instance_a.hit_counter("1.2.3.4:900", 60) == 1
    assert instance_b.hit_counter("1.2.3.4:900", 60) == 2  # the other instance sees it too
    assert instance_a.hit_counter("5.6.7.8:900", 60) == 1  # per client, not global


def test_unreachable_redis_falls_back_to_the_local_store(monkeypatch):
    monkeypatch.setattr(config, "REDIS_URL", "redis://nowhere:6379")
    store.use_backend(None)
    try:
        assert store.backend_name() == "memory"  # degraded, not broken
        document = store.add("contract.txt", 0, sample_chunks())
        assert store.get(document.id) is not None
    finally:
        store.use_backend(store.MemoryBackend())


def test_memory_store_respects_a_byte_budget(monkeypatch):
    """However high MAX_DOCS is set, the heap stays bounded."""
    backend = store.MemoryBackend()
    store.use_backend(backend)
    monkeypatch.setattr(config, "MAX_DOCS", 1000)
    monkeypatch.setattr(config, "MAX_MEMORY_BYTES", 12_000)

    for _ in range(12):
        store.add("contract.txt", 0, sample_chunks())

    held = list(backend._documents.values())
    assert sum(document.nbytes for document in held) <= 12_000
    assert 0 < len(held) < 12  # older documents were evicted to stay in budget


def test_memory_store_expires_on_ttl(monkeypatch):
    store.use_backend(store.MemoryBackend())
    document = store.add("contract.txt", 0, sample_chunks())
    monkeypatch.setattr(config, "DOC_TTL_SECONDS", 0)
    time.sleep(0.01)

    assert store.get(document.id) is None
