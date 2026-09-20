"""Pipeline step 4: turn chunks into vectors.

Embeddings are computed locally (ONNX, no API key, no torch) so document text is
never sent anywhere just to be indexed. If the model cannot be loaded - no
network on first run, unsupported platform, tests - we fall back to a
dependency-free hashing embedding so the app still works, with weaker recall.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading

import numpy as np

from backend import config

log = logging.getLogger(__name__)

_HASH_DIM = 512
_TOKEN = re.compile(r"[a-z0-9]+")

_lock = threading.Lock()
_model = None
_backend: str | None = None


def backend_name() -> str:
    """Which embedding backend is live: ``fastembed`` or ``hash``."""
    _load()
    return _backend or "hash"


def _load() -> None:
    global _model, _backend
    if _backend:
        return
    with _lock:
        if _backend:
            return
        if config.EMBEDDINGS == "fastembed":
            try:
                from fastembed import TextEmbedding

                _model = TextEmbedding(model_name=config.EMBEDDING_MODEL)
                _backend = "fastembed"
                return
            except Exception as exc:  # noqa: BLE001 - any failure must stay non-fatal
                log.warning("fastembed unavailable (%s); using hashing embeddings", exc)
        _backend = "hash"


def embed_documents(texts: list[str]) -> np.ndarray:
    """Embed document chunks. Returns an L2-normalised ``(n, dim)`` float32 array."""
    _load()
    if _backend == "fastembed":
        return _normalise(np.asarray(list(_model.embed(texts)), dtype="float32"))
    return _hash_embed(texts)


def embed_query(text: str) -> np.ndarray:
    """Embed a user question. Returns a ``(1, dim)`` float32 array."""
    _load()
    if _backend == "fastembed":
        return _normalise(np.asarray(list(_model.query_embed(text)), dtype="float32"))
    return _hash_embed([text])


def _hash_embed(texts: list[str]) -> np.ndarray:
    vectors = np.zeros((len(texts), _HASH_DIM), dtype="float32")
    for row, text in enumerate(texts):
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.blake2b(token.encode(), digest_size=4).digest()
            vectors[row, int.from_bytes(digest, "big") % _HASH_DIM] += 1.0
    return _normalise(np.log1p(vectors))


def _normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, 1e-9)
