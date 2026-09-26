"""Runtime configuration, read once from the environment.

Values are module attributes on purpose: code refers to them as ``config.NAME``
so tests can monkeypatch a single limit without re-importing the world.
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# --- LLM -------------------------------------------------------------------
# Any OpenAI-compatible /chat/completions endpoint. Default is Gemini's.
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv(
    "LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
).rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))

# --- Web -------------------------------------------------------------------
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()
]

# --- Limits ----------------------------------------------------------------
MAX_UPLOAD_BYTES = _int("MAX_UPLOAD_MB", 10) * 1024 * 1024
MAX_PAGES = _int("MAX_PAGES", 120)
OCR_MAX_PAGES = _int("OCR_MAX_PAGES", 10)
DOC_TTL_SECONDS = _int("DOC_TTL_MINUTES", 30) * 60
MAX_DOCS = _int("MAX_DOCS", 50)
# Hard ceiling on what the in-process store may hold, independent of MAX_DOCS.
MAX_MEMORY_BYTES = _int("MAX_MEMORY_MB", 256) * 1024 * 1024
RATE_LIMIT_PER_MINUTE = _int("RATE_LIMIT_PER_MINUTE", 30)
MAX_QUESTION_CHARS = 1000

# --- Shared state ----------------------------------------------------------
# Set this and documents, caches and rate limits move out of the process, so
# the API can run on more than one instance. Unset, everything stays local.
REDIS_URL = os.getenv("REDIS_URL", "").strip()

# --- Retrieval -------------------------------------------------------------
EMBEDDINGS = os.getenv("EMBEDDINGS", "fastembed")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
RETRIEVAL_TOP_K = _int("RETRIEVAL_TOP_K", 4)
