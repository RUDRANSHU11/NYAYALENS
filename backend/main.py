"""NyayaLens API entry point.

Run it with:  uvicorn backend.main:app --reload
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend import __version__, config
from backend.api.routes import router
from backend.document_processing.extract import DocumentError
from backend.services.llm import LLMError

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
# Uploaded document text is never logged - only ids, sizes and outcomes.
log = logging.getLogger("nyayalens")

DISCLAIMER = (
    "NyayaLens is an informational and educational tool. It does not provide legal "
    "representation or replace a qualified lawyer. AI-generated explanations may contain "
    "errors - consult a qualified legal professional before acting on anything here."
)

app = FastAPI(
    title="NyayaLens API",
    version=__version__,
    summary="See the law clearly - GenAI legal document assistant.",
    description=(
        "Upload a legal document, get plain-language explanations, important clauses, "
        "answers with source references, and a clause-level comparison of two versions.\n\n"
        f"**Disclaimer:** {DISCLAIMER}"
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
    allow_credentials=False,  # no cookies, no sessions - the doc id is the only handle
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(DocumentError)
async def document_error_handler(_: Request, exc: DocumentError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.exception_handler(LLMError)
async def llm_error_handler(_: Request, exc: LLMError) -> JSONResponse:
    log.warning("LLM error: %s", exc)
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/", tags=["meta"])
def index() -> dict:
    return {
        "name": "NyayaLens",
        "tagline": "See the law clearly.",
        "version": __version__,
        "docs": "/docs",
        "disclaimer": DISCLAIMER,
    }


app.include_router(router)
