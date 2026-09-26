"""Pipeline steps 5-6: vector storage and retrieval.

A document lives behind an unguessable id and expires after ``DOC_TTL_MINUTES``.
Two interchangeable backends, selected by whether ``REDIS_URL`` is set:

* **memory** (default) - one process, bounded by document count *and* total
  bytes, so a generous ``MAX_DOCS`` or ``MAX_PAGES`` cannot exhaust the heap.
* **redis** - documents, their caches and the rate-limit counters live outside
  the process, so any instance can serve any request and the API scales
  horizontally without losing state.

Neither backend writes to disk, both expire entries on the same TTL, and
serialisation is JSON plus raw float32 - never pickle, so a compromised store
cannot execute code here.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import faiss
import numpy as np

from backend import config
from backend.document_processing.chunking import Chunk
from backend.rag import embeddings

log = logging.getLogger(__name__)

MAX_CACHED_ANSWERS = 100
PREFIX = "nyaya"


@dataclass
class StoredDocument:
    id: str
    name: str
    pages: int
    chunks: list[Chunk]
    vectors: np.ndarray
    created_at: float
    ocr_used: bool = False
    flags: dict[str, list[str]] = field(default_factory=dict)
    _index: faiss.Index | None = field(default=None, init=False, repr=False)
    _by_id: dict[str, Chunk] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._by_id = {chunk.id: chunk for chunk in self.chunks}

    @property
    def index(self) -> faiss.Index:
        """FAISS index, built on first use - a document read back from Redis
        arrives as vectors, and rebuilding an exact index is microseconds."""
        if self._index is None:
            index = faiss.IndexFlatIP(self.vectors.shape[1])
            index.add(self.vectors)
            self._index = index
        return self._index

    @property
    def expires_in(self) -> int:
        return max(0, int(self.created_at + config.DOC_TTL_SECONDS - time.time()))

    @property
    def nbytes(self) -> int:
        """Roughly what this document costs in memory: vectors plus text."""
        return int(self.vectors.nbytes) + sum(len(chunk.text) for chunk in self.chunks)

    def chunk(self, chunk_id: str) -> Chunk | None:
        return self._by_id.get(chunk_id)


# --- serialisation (used by the Redis backend) -----------------------------


def dumps(document: StoredDocument) -> bytes:
    header = json.dumps(
        {
            "id": document.id,
            "name": document.name,
            "pages": document.pages,
            "ocr_used": document.ocr_used,
            "created_at": document.created_at,
            "flags": document.flags,
            "dims": int(document.vectors.shape[1]),
            "chunks": [
                {
                    "id": chunk.id,
                    "text": chunk.text,
                    "page": chunk.page,
                    "section": chunk.section,
                    "clause": chunk.clause,
                }
                for chunk in document.chunks
            ],
        }
    ).encode()
    return len(header).to_bytes(4, "big") + header + document.vectors.tobytes()


def loads(blob: bytes) -> StoredDocument:
    size = int.from_bytes(blob[:4], "big")
    meta = json.loads(blob[4 : 4 + size])
    vectors = np.ascontiguousarray(
        np.frombuffer(blob[4 + size :], dtype="float32").reshape(-1, meta["dims"])
    )
    return StoredDocument(
        id=meta["id"],
        name=meta["name"],
        pages=meta["pages"],
        chunks=[Chunk(**chunk) for chunk in meta["chunks"]],
        vectors=vectors,
        created_at=meta["created_at"],
        ocr_used=meta["ocr_used"],
        flags=meta["flags"],
    )


# --- backends --------------------------------------------------------------


class MemoryBackend:
    """Per-process store, bounded by document count and by total bytes."""

    name = "memory"

    def __init__(self) -> None:
        self._documents: "OrderedDict[str, StoredDocument]" = OrderedDict()
        self._caches: dict[str, dict[str, dict]] = {}
        self._lock = threading.Lock()

    def put(self, document: StoredDocument) -> None:
        with self._lock:
            self._purge()
            self._documents[document.id] = document
            while len(self._documents) > config.MAX_DOCS:
                self._evict()
            # A byte budget, not just a count: however high MAX_DOCS or
            # MAX_PAGES are set, the oldest documents go before the heap fills.
            while (
                len(self._documents) > 1
                and sum(item.nbytes for item in self._documents.values())
                > config.MAX_MEMORY_BYTES
            ):
                self._evict()

    def fetch(self, document_id: str) -> StoredDocument | None:
        with self._lock:
            document = self._documents.get(document_id)
            if document is None:
                return None
            if document.created_at < time.time() - config.DOC_TTL_SECONDS:
                self._forget(document_id)
                return None
            return document

    def drop(self, document_id: str) -> bool:
        with self._lock:
            return self._forget(document_id)

    def count(self) -> int:
        with self._lock:
            self._purge()
            return len(self._documents)

    def clear(self) -> None:
        with self._lock:
            self._documents.clear()
            self._caches.clear()

    def cached(self, document_id: str, kind: str, key: str) -> dict | None:
        return self._caches.get(document_id, {}).get(f"{kind}:{key}")

    def remember(self, document_id: str, kind: str, key: str, value: dict) -> None:
        entries = self._caches.setdefault(document_id, {})
        if len(entries) >= MAX_CACHED_ANSWERS:
            entries.pop(next(iter(entries)), None)
        entries[f"{kind}:{key}"] = value

    def _evict(self) -> None:
        document_id, _ = self._documents.popitem(last=False)
        self._caches.pop(document_id, None)

    def _forget(self, document_id: str) -> bool:
        self._caches.pop(document_id, None)
        return self._documents.pop(document_id, None) is not None

    def _purge(self) -> None:
        cutoff = time.time() - config.DOC_TTL_SECONDS
        for document_id in [
            key for key, value in self._documents.items() if value.created_at < cutoff
        ]:
            self._forget(document_id)


class RedisBackend:
    """Shared store: every instance sees the same documents and counters."""

    name = "redis"

    def __init__(self, client) -> None:
        self._client = client

    def put(self, document: StoredDocument) -> None:
        self._client.setex(self._key(document.id), config.DOC_TTL_SECONDS, dumps(document))

    def fetch(self, document_id: str) -> StoredDocument | None:
        blob = self._client.get(self._key(document_id))
        return loads(blob) if blob else None

    def drop(self, document_id: str) -> bool:
        removed = self._client.delete(self._key(document_id))
        self._client.delete(self._cache_key(document_id))
        return bool(removed)

    def count(self) -> int:
        return sum(1 for _ in self._client.scan_iter(match=f"{PREFIX}:doc:*", count=100))

    def clear(self) -> None:
        for key in list(self._client.scan_iter(match=f"{PREFIX}:*", count=100)):
            self._client.delete(key)

    def cached(self, document_id: str, kind: str, key: str) -> dict | None:
        raw = self._client.hget(self._cache_key(document_id), f"{kind}:{key}")
        return json.loads(raw) if raw else None

    def remember(self, document_id: str, kind: str, key: str, value: dict) -> None:
        cache_key = self._cache_key(document_id)
        if self._client.hlen(cache_key) >= MAX_CACHED_ANSWERS:
            return
        self._client.hset(cache_key, f"{kind}:{key}", json.dumps(value))
        self._client.expire(cache_key, config.DOC_TTL_SECONDS)

    def hit_counter(self, key: str, window_seconds: int) -> int:
        """Atomic per-window counter, so a rate limit holds across instances."""
        full_key = f"{PREFIX}:rl:{key}"
        count = int(self._client.incr(full_key))
        if count == 1:
            self._client.expire(full_key, window_seconds)
        return count

    @staticmethod
    def _key(document_id: str) -> str:
        return f"{PREFIX}:doc:{document_id}"

    @staticmethod
    def _cache_key(document_id: str) -> str:
        return f"{PREFIX}:cache:{document_id}"


_backend: MemoryBackend | RedisBackend | None = None
_backend_lock = threading.Lock()


def backend() -> MemoryBackend | RedisBackend:
    global _backend
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                _backend = _build_backend()
    return _backend


def use_backend(new_backend: MemoryBackend | RedisBackend | None) -> None:
    """Swap the backend - used by tests and by anything injecting a client."""
    global _backend
    _backend = new_backend


def backend_name() -> str:
    return backend().name


def _build_backend() -> MemoryBackend | RedisBackend:
    if config.REDIS_URL:
        try:
            import redis

            client = redis.Redis.from_url(config.REDIS_URL, socket_timeout=5)
            client.ping()
            log.info("document store: redis (shared across instances)")
            return RedisBackend(client)
        except Exception as exc:  # noqa: BLE001 - a store outage must not take the app down
            log.warning("redis unavailable (%s); falling back to the in-process store", exc)
    return MemoryBackend()


# --- public API ------------------------------------------------------------


def add(
    name: str,
    pages: int,
    chunks: list[Chunk],
    ocr_used: bool = False,
    flags: dict[str, list[str]] | None = None,
) -> StoredDocument:
    """Embed ``chunks``, index them and keep the document for its TTL."""
    if not chunks:
        raise ValueError("cannot store a document with no chunks")

    document = StoredDocument(
        id=secrets.token_urlsafe(16),
        name=name,
        pages=pages,
        chunks=chunks,
        vectors=embeddings.embed_documents([chunk.text for chunk in chunks]),
        created_at=time.time(),
        ocr_used=ocr_used,
        flags=flags or {},
    )
    backend().put(document)
    return document


def get(document_id: str) -> StoredDocument | None:
    return backend().fetch(document_id)


def delete(document_id: str) -> bool:
    return backend().drop(document_id)


def clear() -> None:
    backend().clear()


def count() -> int:
    return backend().count()


def cached(document_id: str, kind: str, key: str) -> dict | None:
    return backend().cached(document_id, kind, key)


def remember(document_id: str, kind: str, key: str, value: dict) -> None:
    backend().remember(document_id, kind, key, value)


def search(
    document: StoredDocument, query: str, top_k: int | None = None
) -> list[tuple[Chunk, float]]:
    """Return the ``top_k`` chunks most relevant to ``query``, best first."""
    limit = min(top_k or config.RETRIEVAL_TOP_K, len(document.chunks))
    if limit <= 0:
        return []
    scores, ids = document.index.search(embeddings.embed_query(query), limit)
    return [
        (document.chunks[int(position)], float(score))
        for score, position in zip(scores[0], ids[0], strict=True)
        if position >= 0
    ]


__all__ = [
    "StoredDocument",
    "MemoryBackend",
    "RedisBackend",
    "add",
    "get",
    "delete",
    "clear",
    "count",
    "cached",
    "remember",
    "search",
    "backend",
    "backend_name",
    "use_backend",
    "dumps",
    "loads",
]
