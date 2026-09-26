"""Download the embedding model at build time, into the deployment bundle.

Without this, every cold instance fetches ~70 MB from Hugging Face before it can
answer its first question. The app picks the directory up automatically (see
backend/rag/embeddings.py).

Not used on Vercel: the model pushes the function past its 500 MB limit (measured
at 593.86 MB). Run it in the build for hosts without that cap - Render, Railway,
Docker - or locally to warm the cache before a demo:

    python scripts/fetch_model.py
"""

import os
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / ".model-cache"


def main() -> int:
    model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    TARGET.mkdir(exist_ok=True)
    try:
        from fastembed import TextEmbedding

        TextEmbedding(model_name=model, cache_dir=str(TARGET))
    except Exception as exc:  # noqa: BLE001 - never fail the build over a cache warm-up
        print(f"could not pre-cache {model}: {exc}; it will download at runtime instead")
        return 0
    size = sum(path.stat().st_size for path in TARGET.rglob("*") if path.is_file())
    print(f"cached {model} in {TARGET} ({size / 1_000_000:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
