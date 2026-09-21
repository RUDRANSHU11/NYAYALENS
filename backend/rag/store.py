"""Pipeline steps 5-6: vector storage and retrieval.

Documents live in memory only, behind an unguessable id, and expire after
``DOC_TTL_MINUTES``. Nothing is written to disk and nothing survives a restart -
that is the privacy posture the README asks for, not an oversight.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import faiss

from backend import config
from backend.document_processing.chunking import Chunk
from backend.rag import embeddings

MAX_CACHED_ANSWERS = 100


@dataclass
class StoredDocument:
    id: str
    name: str
    pages: int
    chunks: list[Chunk]
    index: faiss.Index
    created_at: float
    ocr_used: bool = False
    # chunk id -> important-clause categories, computed once at upload.
    flags: dict[str, list[str]] = field(default_factory=dict)
    # (chunk_id, language) -> generated explanation, so we never pay for the same
    # clause twice while the document is alive.
    explanations: dict[tuple[str, str], dict] = field(default_factory=dict)
    # (normalised question, language) -> answer. Bounded: oldest entry dropped first.
    answers: dict[tuple[str, str], object] = field(default_factory=dict)
    _by_id: dict[str, Chunk] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._by_id = {chunk.id: chunk for chunk in self.chunks}

    @property
    def expires_in(self) -> int:
        return max(0, int(self.created_at + config.DOC_TTL_SECONDS - time.time()))

    def chunk(self, chunk_id: str) -> Chunk | None:
        return self._by_id.get(chunk_id)

    def remember_answer(self, key: tuple[str, str], answer: object) -> None:
        if len(self.answers) >= MAX_CACHED_ANSWERS:
            self.answers.pop(next(iter(self.answers)), None)
        self.answers[key] = answer


_documents: "OrderedDict[str, StoredDocument]" = OrderedDict()
_lock = threading.Lock()


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

    vectors = embeddings.embed_documents([chunk.text for chunk in chunks])
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)

    document = StoredDocument(
        id=secrets.token_urlsafe(16),
        name=name,
        pages=pages,
        chunks=chunks,
        index=index,
        created_at=time.time(),
        ocr_used=ocr_used,
        flags=flags or {},
    )
    with _lock:
        _purge_expired()
        while len(_documents) >= config.MAX_DOCS:
            _documents.popitem(last=False)
        _documents[document.id] = document
    return document


def get(document_id: str) -> StoredDocument | None:
    with _lock:
        _purge_expired()
        return _documents.get(document_id)


def delete(document_id: str) -> bool:
    with _lock:
        return _documents.pop(document_id, None) is not None


def clear() -> None:
    with _lock:
        _documents.clear()


def count() -> int:
    with _lock:
        _purge_expired()
        return len(_documents)


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


def _purge_expired() -> None:
    """Drop documents past their TTL. Caller holds ``_lock``."""
    cutoff = time.time() - config.DOC_TTL_SECONDS
    for document_id in [
        document_id
        for document_id, document in _documents.items()
        if document.created_at < cutoff
    ]:
        del _documents[document_id]


__all__ = ["StoredDocument", "add", "get", "delete", "clear", "count", "search"]
