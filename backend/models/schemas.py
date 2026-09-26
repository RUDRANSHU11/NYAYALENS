"""Request and response shapes. These also generate the OpenAPI docs at /docs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend import config

Language = Literal["en", "hi"]


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=config.MAX_QUESTION_CHARS)
    language: Language = "en"


class LanguageRequest(BaseModel):
    language: Language = "en"


class ClauseOut(BaseModel):
    id: str
    text: str
    page: int | None = None
    section: str | None = None
    clause: str | None = None
    reference: str
    categories: list[str] = []


class DocumentOut(BaseModel):
    id: str
    name: str
    pages: int
    chunk_count: int
    important_count: int
    ocr_used: bool
    expires_in: int
    ai_enabled: bool
    clauses: list[ClauseOut]
    category_notes: dict[str, str]


class ExplanationOut(BaseModel):
    chunk_id: str
    reference: str
    original: str
    explanation: str
    obligations: list[str] = []
    rights: list[str] = []
    watch_out: list[str] = []
    language: Language = "en"
    ai_used: bool = True


class SourceOut(BaseModel):
    chunk_id: str
    reference: str
    page: int | None = None
    section: str | None = None
    clause: str | None = None
    text: str
    score: float
    cited: bool = False


class AnswerOut(BaseModel):
    answer: str
    grounded: bool
    ai_used: bool
    language: Language = "en"
    sources: list[SourceOut] = []
    notice: str | None = None


class ValueChangeOut(BaseModel):
    kind: str
    before: str | None = None
    after: str | None = None


class SegmentOut(BaseModel):
    op: str
    text: str


class ChangeOut(BaseModel):
    id: str
    kind: str
    label: str
    reference_before: str | None = None
    reference_after: str | None = None
    text_before: str | None = None
    text_after: str | None = None
    categories: list[str] = []
    values: list[ValueChangeOut] = []
    diff: list[SegmentOut] = []
    obligation_changed: bool = False
    significant: bool = False
    impact: str | None = None


class ComparisonOut(BaseModel):
    name_before: str
    name_after: str
    added: int
    removed: int
    modified: int
    unchanged: int
    ai_used: bool
    language: Language = "en"
    changes: list[ChangeOut]


class HealthOut(BaseModel):
    status: str
    ai_enabled: bool
    model: str | None = None
    embeddings: str
    store: str
    documents_stored: int
    document_ttl_minutes: int
