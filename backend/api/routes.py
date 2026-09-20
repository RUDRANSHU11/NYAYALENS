"""HTTP surface. Thin: validate, call a service, shape the response.

Endpoints are plain ``def`` so FastAPI runs them in its worker threadpool - the
work here is CPU-bound parsing and blocking HTTP to the model provider, which is
exactly what that pool is for.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile

from backend import config
from backend.document_processing import extract
from backend.document_processing.chunking import Chunk, chunk_document
from backend.document_processing.extract import DocumentError, Line
from backend.models.schemas import (
    AnswerOut,
    AskRequest,
    ChangeOut,
    ClauseOut,
    ComparisonOut,
    DocumentOut,
    ExplanationOut,
    HealthOut,
    Language,
    LanguageRequest,
    SourceOut,
)
from backend.rag import embeddings, store
from backend.services import analysis, clauses, compare as compare_service, llm
from backend.api import ratelimit

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_NO_AI_NOTICE = (
    "AI explanations are switched off on this server. "
    "The most relevant clauses from your document are shown below."
)


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(
        status="ok",
        ai_enabled=llm.is_configured(),
        model=config.LLM_MODEL if llm.is_configured() else None,
        embeddings=embeddings.backend_name(),
        documents_in_memory=store.count(),
        document_ttl_minutes=config.DOC_TTL_SECONDS // 60,
    )


@router.post("/documents", response_model=DocumentOut, status_code=201)
def upload_document(request: Request, file: UploadFile = File(...)) -> DocumentOut:
    """Steps 1-5: upload, extract, chunk, embed, store."""
    ratelimit.check(request)
    name = _safe_name(file.filename)
    chunks, pages, ocr_used = _prepare(name, _read_upload(request, file))
    document = store.add(name=name, pages=pages, chunks=chunks, ocr_used=ocr_used)
    return _document_payload(document)


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: str) -> DocumentOut:
    return _document_payload(_require(document_id))


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str) -> Response:
    """Let the user drop their document before the TTL does."""
    store.delete(document_id)
    return Response(status_code=204)


@router.post(
    "/documents/{document_id}/clauses/{chunk_id}/explain", response_model=ExplanationOut
)
def explain_clause(
    request: Request, document_id: str, chunk_id: str, payload: LanguageRequest
) -> ExplanationOut:
    """Feature 1: plain-language explanation of one clause, cached per language."""
    ratelimit.check(request)
    document = _require(document_id)
    chunk = document.chunk(chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="Clause not found in this document.")
    if not llm.is_configured():
        raise HTTPException(status_code=503, detail=_NO_AI_NOTICE)

    cache_key = (chunk_id, payload.language)
    explanation = document.explanations.get(cache_key)
    if explanation is None:
        explanation = analysis.explain_clause(chunk, payload.language)
        document.explanations[cache_key] = explanation

    return ExplanationOut(
        chunk_id=chunk.id,
        reference=chunk.reference,
        original=chunk.text,
        language=payload.language,
        **explanation,
    )


@router.post("/documents/{document_id}/ask", response_model=AnswerOut)
def ask_document(request: Request, document_id: str, payload: AskRequest) -> AnswerOut:
    """Features 4-5: retrieve relevant clauses, then answer from them with citations."""
    ratelimit.check(request)
    document = _require(document_id)
    contexts = store.search(document, payload.question)

    answer, grounded, ai_used, notice, cited = "", False, False, None, []
    if not llm.is_configured():
        notice = _NO_AI_NOTICE
    else:
        try:
            result = analysis.answer_question(payload.question, contexts, payload.language)
            answer, grounded, cited, ai_used = (
                result["answer"],
                result["grounded"],
                result["citations"],
                True,
            )
        except llm.LLMError as exc:
            log.warning("answer generation failed: %s", exc)
            notice = f"{exc} The most relevant clauses are shown below."

    return AnswerOut(
        answer=answer,
        grounded=grounded,
        ai_used=ai_used,
        language=payload.language,
        notice=notice,
        sources=[
            SourceOut(
                chunk_id=chunk.id,
                reference=chunk.reference,
                page=chunk.page,
                section=chunk.section,
                clause=chunk.clause,
                text=chunk.text,
                score=round(score, 4),
                cited=chunk.id in cited,
            )
            for chunk, score in contexts
        ],
    )


@router.post("/compare", response_model=ComparisonOut)
def compare_documents(
    request: Request,
    file_a: UploadFile = File(..., description="The older version"),
    file_b: UploadFile = File(..., description="The newer version"),
    language: Language = Form("en"),
) -> ComparisonOut:
    """Feature 2: align two versions and report what changed."""
    ratelimit.check(request)
    name_a, name_b = _safe_name(file_a.filename), _safe_name(file_b.filename)
    chunks_a, _, _ = _prepare(name_a, _read_upload(request, file_a))
    chunks_b, _, _ = _prepare(name_b, _read_upload(request, file_b))

    result = compare_service.compare(chunks_a, chunks_b)

    impacts: dict[str, str] = {}
    if llm.is_configured() and result.changes:
        try:
            impacts = analysis.explain_changes(result.changes, language)
        except llm.LLMError as exc:  # the diff itself is still worth returning
            log.warning("change explanation failed: %s", exc)

    return ComparisonOut(
        name_before=name_a,
        name_after=name_b,
        added=result.added,
        removed=result.removed,
        modified=result.modified,
        unchanged=result.unchanged,
        ai_used=bool(impacts),
        language=language,
        changes=[
            ChangeOut(
                id=change.id,
                kind=change.kind,
                label=change.label,
                reference_before=change.reference_before,
                reference_after=change.reference_after,
                text_before=change.text_before,
                text_after=change.text_after,
                categories=change.categories,
                values=[vars(value) for value in change.values],
                diff=[vars(segment) for segment in change.diff],
                obligation_changed=change.obligation_changed,
                significant=change.significant,
                impact=impacts.get(change.id),
            )
            for change in result.changes
        ],
    )


def _prepare(name: str, data: bytes) -> tuple[list[Chunk], int, bool]:
    """Bytes in, indexed-ready chunks out (steps 2-3, with OCR when needed)."""
    extracted = extract.extract(name, data)
    ocr_used = False

    if extracted.needs_ocr:
        if not llm.is_configured():
            raise DocumentError(
                "This looks like a scanned document with no text layer, and OCR needs an AI "
                "provider configured on the server.",
                422,
            )
        lines: list[Line] = []
        for number, text in enumerate(analysis.ocr_pages(extracted.page_images), start=1):
            lines.extend(
                Line(page=number, text=" ".join(raw.split()))
                for raw in text.splitlines()
                if raw.strip()
            )
        extracted.lines = lines
        ocr_used = True

    chunks = chunk_document(extracted.lines)
    if not chunks:
        raise DocumentError("No readable text was found in this document.", 422)
    return chunks, extracted.pages, ocr_used


def _document_payload(document: store.StoredDocument) -> DocumentOut:
    flags = clauses.flag(document.chunks)
    return DocumentOut(
        id=document.id,
        name=document.name,
        pages=document.pages,
        chunk_count=len(document.chunks),
        important_count=len(flags),
        ocr_used=document.ocr_used,
        expires_in=document.expires_in,
        ai_enabled=llm.is_configured(),
        category_notes=clauses.CATEGORY_NOTES,
        clauses=[
            ClauseOut(
                id=chunk.id,
                text=chunk.text,
                page=chunk.page,
                section=chunk.section,
                clause=chunk.clause,
                reference=chunk.reference,
                categories=flags.get(chunk.id, []),
            )
            for chunk in document.chunks
        ],
    )


def _require(document_id: str) -> store.StoredDocument:
    document = store.get(document_id)
    if document is None:
        raise HTTPException(
            status_code=404,
            detail="This document is no longer on the server. Please upload it again.",
        )
    return document


def _read_upload(request: Request, file: UploadFile) -> bytes:
    """Read an upload, refusing anything over the limit before it is parsed."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > config.MAX_UPLOAD_BYTES * 2 + 8192:
        raise DocumentError("The upload is larger than the size limit.", 413)

    data = file.file.read(config.MAX_UPLOAD_BYTES + 1)
    file.file.close()
    if len(data) > config.MAX_UPLOAD_BYTES:
        limit = config.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise DocumentError(f"File is larger than the {limit} MB limit.", 413)
    return data


def _safe_name(name: str | None) -> str:
    """A display-safe file name: no paths, no control characters, bounded length."""
    base = os.path.basename(name or "").strip()
    cleaned = "".join(character for character in base if character.isprintable())
    return cleaned[:120] or "document"
