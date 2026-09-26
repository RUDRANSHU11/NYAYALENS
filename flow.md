# flow.md — how NyayaLens actually works

Orientation map for the codebase: what runs where, in what order, and which direction new code
should follow. Pairs with [decisions.md](decisions.md) (*why* it is like this).

---

## 1. What this is

A web app for people with no legal training. You upload a legal document (employment agreement,
rental agreement, contract, privacy policy, terms of service). The backend splits it into clauses,
flags the ones that usually matter, and answers questions about it in plain language — always
showing the clause, section and page the answer came from. A second mode compares two versions of
the same contract and reports what changed.

---

## 2. Stack

| Layer | Choice | What it does here |
|-------|--------|-------------------|
| Frontend | Next.js 16 (Pages Router) + React 19 + TypeScript | two pages, no global state library |
| Styling | Tailwind CSS 4 | utility classes, one small `@theme` block in `frontend/styles/globals.css` |
| API | FastAPI + Pydantic | validation, OpenAPI docs, async handlers + threadpool for CPU work |
| PDF/DOCX | PyMuPDF, python-docx | text + page numbers, tables, heading styles |
| Embeddings | fastembed (ONNX `bge-small-en-v1.5`) | local vectors, no API key; hashing fallback |
| Vector index | FAISS `IndexFlatIP` | exact cosine search over one document |
| LLM | any OpenAI-compatible endpoint (Gemini default) | explanations, answers, change impact, OCR |
| Tests | pytest + FastAPI TestClient | 94 tests, no network |

---

## 3. Directory map

```
nyayalens/
├── backend/
│   ├── main.py                     FastAPI app, CORS, security headers, error handlers
│   ├── config.py                   every env-driven setting, read once
│   ├── api/
│   │   ├── routes.py               all HTTP endpoints (thin)
│   │   └── ratelimit.py            per-IP fixed-window throttle
│   ├── models/schemas.py           Pydantic request/response shapes
│   ├── document_processing/
│   │   ├── extract.py              validation + PDF/DOCX/TXT text extraction
│   │   └── chunking.py             clause-aware chunking + `Chunk.reference`
│   ├── rag/
│   │   ├── embeddings.py           fastembed with a hashing fallback
│   │   └── store.py                document store (memory or Redis) + FAISS search
│   └── services/
│       ├── clauses.py              rule-based important-clause categories
│       ├── compare.py              contract comparison engine
│       ├── llm.py                  transport to the model provider
│       └── analysis.py             the four prompts (explain, answer, impact, OCR)
├── frontend/
│   ├── pages/                      index.tsx (understand + ask), compare.tsx, _app, _document
│   ├── components/                 Layout, ClauseList, AskPanel, DiffText, FileField, Notice
│   ├── services/api.ts             typed fetch client, all API types
│   └── styles/globals.css          Tailwind import, theme tokens, focus/ins/del styles
├── scripts/fetch_model.py          build-time download of the embedding model
├── data/                           two sample contract versions for demos and tests
├── tests/                          pytest suite (conftest.py is at the repo root)
└── requirements.txt (runtime) / requirements-dev.txt (+ pytest) / .env.example
```

---

## 4. Runtime flows

### A. Upload and analyse (`POST /api/documents`)

1. [`routes.upload_document`](backend/api/routes.py:58) — rate limit, sanitise the filename,
   read the body with a hard size cap ([`_read_upload`](backend/api/routes.py:271)).
2. [`routes._prepare`](backend/api/routes.py:206) drives the pipeline:
   - [`extract.extract`](backend/document_processing/extract.py:56) validates (extension, magic
     bytes, size, page count, zip expansion) and returns `Line(page, text, heading)` items.
   - If the PDF has no text layer, pages are rendered to PNG and sent to
     [`analysis.ocr_pages`](backend/services/analysis.py:132); with no model configured this is a
     clean 422 instead of an empty document.
   - [`chunk_document`](backend/document_processing/chunking.py:81) starts a new chunk at a clause
     number, a heading, or the size limit, carrying page/section/clause metadata.
3. [`store.add`](backend/rag/store.py:48) embeds the chunks
   ([`embed_documents`](backend/rag/embeddings.py:55)), builds a FAISS index, and keeps the
   document under a `secrets.token_urlsafe(16)` id with a TTL.
4. [`routes._document_payload`](backend/api/routes.py:234) tags every chunk through
   [`clauses.flag`](backend/services/clauses.py:111) and returns clauses + category notes.
5. `frontend/pages/index.tsx` stores the payload, moves focus to the results heading, and renders
   `ClauseList` + `AskPanel`.

### B. Explain a clause (`POST /api/documents/{id}/clauses/{chunk_id}/explain`)

1. [`routes.explain_clause`](backend/api/routes.py:82) resolves the document and chunk, and
   returns 503 when no model is configured (the UI disables the button in that case).
2. Cache hit on `(chunk_id, language)` in `StoredDocument.explanations` → returned immediately.
3. Otherwise [`analysis.explain_clause`](backend/services/analysis.py:37) sends the guardrail
   system prompt + the fenced clause, and parses the JSON reply
   ([`llm.complete_json`](backend/services/llm.py:92)).

### C. Ask a question (`POST /api/documents/{id}/ask`)

1. [`routes.ask_document`](backend/api/routes.py:110); Pydantic caps the question at 1000 chars.
2. [`store.search`](backend/rag/store.py:96) embeds the question and pulls the top `RETRIEVAL_TOP_K`
   chunks from FAISS.
3. [`analysis.answer_question`](backend/services/analysis.py:63) numbers those chunks, asks for an
   answer plus citation numbers, and maps the numbers back to chunk ids.
4. Real answers are cached per `(normalised question, language)`, bounded to 100 per document,
   so a repeated question skips retrieval and the model entirely.
5. The response always carries `sources`; if the model is off or fails, `ai_used=false`, `notice`
   explains why, and the retrieved clauses still answer "where is this in my document?".

### D. Compare two versions (`POST /api/compare`)

1. [`routes.compare_documents`](backend/api/routes.py:155) runs both files through the same
   `_prepare` pipeline (no storage — comparison is stateless).
2. [`compare.compare`](backend/services/compare.py:106) aligns the two clause lists with
   `difflib.SequenceMatcher`; `replace` blocks are paired by similarity above `PAIR_THRESHOLD`,
   anything below becomes an add + a remove.
3. Each pair gets a word-level diff ([`word_diff`](backend/services/compare.py:137)), extracted
   value changes ([`value_changes`](backend/services/compare.py:151): amounts, durations,
   percentages, dates), clause categories, and an obligation flag from modal verbs.
4. Significant changes go to [`analysis.explain_changes`](backend/services/analysis.py:102) in one
   batched call; failure there degrades to a diff with no impact text.

---

## 5. Data model

Nothing is persisted to disk. State lives behind the store interface in `backend/rag/store.py`:
`MemoryBackend` (an `OrderedDict` guarded by a lock, bounded by count *and* bytes) or
`RedisBackend` (`nyaya:doc:*` and `nyaya:cache:*` keys with the same TTL) when `REDIS_URL` is
set. Swap them with `store.use_backend(...)`; everything above calls the module functions:

```
StoredDocument
  id            secrets.token_urlsafe(16)
  name/pages    display metadata
  chunks        list[Chunk(id, text, page, section, clause)]
  index         faiss.IndexFlatIP, one row per chunk, same order
  created_at    drives expiry (DOC_TTL_SECONDS) and FIFO eviction (MAX_DOCS)
  flags         {chunk_id: [categories]}, computed once at upload
  explanations  {(chunk_id, language): explanation}
  answers       {(normalised question, language): AnswerOut}, max 100, oldest dropped
```

`Chunk.reference` (`"Clause 5.2 · Page 3"`) is the single source of truth for citations — the UI
never builds its own.

---

## 6. Conventions

- **Routes stay thin.** Validate, call one service, shape a Pydantic model. Logic belongs in
  `services/` or `document_processing/`.
- **Async for I/O, threadpool for CPU.** Handlers are `async def`; model calls are awaited;
  anything CPU-bound (extract, chunk, embed, compare, flag) goes through `run_in_threadpool`.
  Never call a blocking function directly inside a handler.
- **Config through `backend/config.py`,** referenced as `config.NAME` (never `from config import
  NAME`) so tests can monkeypatch one limit.
- **Deterministic first.** If a feature can be done with regex/difflib, do it there and use the
  model only to phrase things. Every model-backed feature needs a sensible no-key path.
- **Errors:** raise `DocumentError(message, status_code)` for anything the user can fix; `LLMError`
  for provider trouble. Both have handlers in `backend/main.py`. Messages are user-facing — no
  stack traces, no provider internals.
- **Privacy:** never log document text; never write an upload to disk.
- **Prompts** live in `services/analysis.py` only, always with the `_GUARDRAILS` system message and
  the document fenced in `<document_extract>`.
- **Frontend:** one component per file, props typed inline, all API types in `services/api.ts`.
  Native HTML elements over ARIA widgets; every control has a label; results land in an
  `aria-live` region; diffs use `<ins>`/`<del>` with `sr-only` text so colour is never the only
  signal.
- **Tests** mirror the module they cover (`tests/test_<module>.py`) and must not need a network.

---

## 7. Run it

```bash
# backend
pip install -r requirements-dev.txt   # runtime deps + pytest
uvicorn backend.main:app --reload --port 8000

# frontend
cd frontend && npm install && npm run dev

# checks
python -m pytest -q
cd frontend && npm run typecheck
```

Deploy: `vercel deploy` from the repo root. `vercel.json` ships both tiers as one project
(Services): Next.js at `/`, FastAPI at `/api/*`, same origin. Set `LLM_API_KEY` in the Vercel
project's env vars to turn the AI features on. A cold instance downloads the embedding model into
`/tmp` on its first request unless `EMBEDDINGS=hash`.

---

## 8. Current state

**Live:** https://nyayalens-pied.vercel.app (no `LLM_API_KEY` set yet, so AI text is off).

**Works:** upload (PDF/DOCX/TXT), clause chunking with page/section/clause references, 14-category
clause flagging, local embeddings + FAISS retrieval, grounded Q&A with citations, per-clause
plain-language explanation (English/Hindi), two-version comparison with value and obligation
changes, OCR for scanned PDFs, TTL + manual delete, rate limiting, 94 passing tests.

**Stubbed / deliberate limits:** in-process store and rate limiter (single instance only);
comparison pairing is capped at 40×40 clauses per changed block; OCR covers the first
`OCR_MAX_PAGES` pages; language support is English and Hindi only.

**Not built (future scope from the brief):** document summarisation, risk profiling, voice input,
external legal databases, lawyer handoff.
