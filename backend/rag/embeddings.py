"""Pipeline step 4: turn chunks into vectors.

Embeddings are computed locally (ONNX, no API key, no torch) so document text is
never sent anywhere just to be indexed. If the model cannot be loaded - no
network on first run, unsupported platform, tests - we fall back to a
dependency-free hashing embedding so the app still works, with weaker recall.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
import zlib
from pathlib import Path

import numpy as np

from backend import config

log = logging.getLogger(__name__)

_HASH_DIM = 512
_TOKEN = re.compile(r"[a-z0-9]+")

_lock = threading.Lock()
_model = None
_backend: str | None = None


def status() -> str:
    """The live embedding backend, without forcing a model load: a health check
    must stay cheap even on a cold instance."""
    return _backend or f"{config.EMBEDDINGS} (loads on first upload)"


def _load() -> None:
    global _model, _backend
    if _backend:
        return
    with _lock:
        if _backend:
            return
        if config.EMBEDDINGS == "fastembed":
            # Serverless hosts (Vercel) only allow writes under the temp dir, and
            # the Hugging Face downloader caches under ~/.cache by default.
            os.environ.setdefault("HF_HOME", os.path.join(tempfile.gettempdir(), "huggingface"))
            try:
                from fastembed import TextEmbedding

                # scripts/fetch_model.py bakes the model in at build time, so a
                # cold instance does not download ~70 MB before its first answer.
                bundled = Path(__file__).resolve().parents[2] / ".model-cache"
                _model = TextEmbedding(
                    model_name=config.EMBEDDING_MODEL,
                    cache_dir=str(bundled) if bundled.is_dir() else None,
                )
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
            # crc32 is a C-speed checksum; this is a bucket index, never a digest.
            vectors[row, zlib.crc32(token.encode()) % _HASH_DIM] += 1.0
    return _normalise(np.log1p(vectors))


def _normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, 1e-9)
