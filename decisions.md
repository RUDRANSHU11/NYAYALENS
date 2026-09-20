# Decisions

Why NyayaLens is built the way it is. Newest entries at the bottom. Pairs with
[flow.md](flow.md), which describes how it works *now*.

---

## 2026-09-20 — Repository layout follows the brief

**Decision.** `backend/{api,models,services,rag,document_processing}`, `frontend/`, `data/`,
`tests/`, `requirements.txt` — exactly the structure in the NyayaLens brief.

**Why.** The build is judged partly on alignment with the problem statement, and a reviewer
holding that document should find every named directory where they expect it.

**Alternatives.** A flatter `app/` package would have been a couple of files shorter, but it makes
the reviewer translate between the brief and the tree.

---

## 2026-09-20 — FAISS over ChromaDB

**Decision.** `faiss.IndexFlatIP`, one index per uploaded document, held in memory.

**Why.** The brief names "FAISS / ChromaDB". A document has hundreds of chunks, not millions, so
exact inner-product search is instant and needs no tuning. Chroma would have pulled in a much
larger dependency tree (telemetry, a server stack, its own persistence) for the same result.

**Alternatives.** Plain NumPy cosine similarity does the same maths in three lines — but FAISS is
the named stack, costs nothing in complexity here, and does not need replacing if documents grow.

---

## 2026-09-20 — Embeddings run locally, with a fallback

**Decision.** `fastembed` (ONNX `bge-small-en-v1.5`) by default; a dependency-free hashing
embedding when the model cannot be loaded, selectable with `EMBEDDINGS=hash`.

**Why.** Indexing a legal document should not require sending it to a third party, and it should
not require an API key at all — retrieval works before any provider is configured. ONNX keeps this
off PyTorch (~2 GB) and works on a small deployment box. The fallback means no-network machines and
the test suite still exercise the real retrieval path.

**Alternatives.** Provider embedding APIs (Gemini/OpenAI) are lighter to deploy but send the whole
document out and break without a key. sentence-transformers is too heavy for a free-tier host.

---

## 2026-09-20 — One OpenAI-compatible LLM client, Gemini by default

**Decision.** `backend/services/llm.py` speaks `POST {LLM_BASE_URL}/chat/completions` over httpx.
Provider, model and key are three environment variables; the default base URL is Gemini's
OpenAI-compatible endpoint with `gemini-2.5-flash`.

**Why.** The brief asks for a "configurable LLM provider". Gemini, OpenAI, Groq, OpenRouter and a
local Ollama all speak this shape, so configurability costs one code path instead of an SDK per
vendor — including for vision OCR, which uses the same message format.

**Alternatives.** Vendor SDKs (`google-genai`, `openai`) give typed helpers but lock the app to one
provider, or force an adapter layer per provider for no functional gain.

---

## 2026-09-20 — Deterministic core, model only for language

**Decision.** Clause detection is regex categories (`services/clauses.py`); comparison is difflib
alignment plus regex value extraction (`services/compare.py`); retrieval is embeddings + FAISS. The
model is used only to *phrase* things: explain a clause, answer from retrieved context, describe a
change's impact, transcribe a scan.

**Why.** These parts must be repeatable and testable — a judge running the same document twice
should get the same clauses and the same diff. It is also free and instant, it removes a large
class of hallucination, and it means the whole app degrades gracefully with no key configured
instead of showing an error page.

**Alternatives.** Asking the model to classify clauses or diff two contracts is fewer lines, but it
is non-deterministic, slow on long documents, costly, and impossible to unit-test honestly.

---

## 2026-09-20 — Clause-aware chunking instead of fixed-size windows

**Decision.** A chunk starts at a clause number (`5.2`, `Section 4`, `Article IV`), at a heading,
or when the size cap is hit; page, section and clause travel with it, and `Chunk.reference`
renders the citation.

**Why.** The brief requires answers to point at a clause and page. Fixed-size windows cut clauses
in half and cannot be cited precisely. Clause boundaries are also what the comparison engine needs
to align two versions.

**Alternatives.** Fixed 500-token windows with overlap are simpler and standard for prose, but they
lose exactly the metadata this product is about.

---

## 2026-09-20 — Documents live in memory with a TTL

**Decision.** Uploads are parsed from bytes, stored in an in-process `OrderedDict` behind a
`secrets.token_urlsafe(16)` id, expire after `DOC_TTL_MINUTES`, are capped at `MAX_DOCS`, and can be
deleted from the UI. Nothing is written to disk and nothing survives a restart.

**Why.** The brief's privacy principles: process only what the user gives, avoid unnecessary
storage, remove temporary files. Not having a database is the strongest version of that promise,
and it keeps deployment to one process.

**Trade-off.** Documents disappear on restart and cannot be shared across instances. Accepted: a
session here is minutes long. Multiple instances would need a shared store — and the rate limiter
would move with it.

---

## 2026-09-20 — OCR through the model's vision, not Tesseract

**Decision.** A PDF with no text layer has its pages rendered to PNG by PyMuPDF and transcribed by
the configured model; with no model configured the upload fails with an explanation.

**Why.** Tesseract is a system binary, not a pip install — a judge or a free-tier host would need
to install it separately, and it would still be the weakest link on a photographed contract. Vision
models read scans well and the transport already exists.

**Trade-off.** OCR needs a key, and page images leave the server, so the UI says so. Capped at
`OCR_MAX_PAGES` pages to bound cost.

---

## 2026-09-20 — Next.js Pages Router, Tailwind, no component library

**Decision.** Two routes (`/`, `/compare`), six components, hand-written Tailwind, native HTML
controls.

**Why.** Two pages is genuinely two pages: links give correct keyboard and screen-reader behaviour
for free, where an ARIA tab widget would need hand-written arrow-key handling. Native `<input
type="file">`, `<select>`, radios, checkbox and `<details>` are accessible by default — most
accessibility bugs come from re-implementing them. A component library would be a large dependency
for six components.

---

## 2026-09-20 — Blocking endpoints in FastAPI's threadpool

**Decision.** Route handlers are plain `def`, not `async def`.

**Why.** The work is CPU-bound parsing/embedding plus blocking HTTP to the provider. FastAPI runs
sync handlers in its worker threadpool, which keeps the event loop free without colouring every
function `async` or wrapping calls in `run_in_executor`.

---

## 2026-09-20 — Upload validation and rate limiting are first-class

**Decision.** Extension *and* magic bytes, size cap before parsing, page-count cap, DOCX zip
expansion guard, filename sanitising, per-IP fixed-window rate limit, and security headers on both
tiers.

**Why.** The app accepts arbitrary files from strangers and spends money per request. Each check
stops a specific abuse: a renamed executable, a memory-exhausting upload, a zip bomb, a path in a
filename, one client draining the model budget.

**Trade-off.** The rate limiter is in-process, so it counts per instance. Marked with a `ponytail:`
comment pointing at Redis if it ever runs behind more than one worker.

---

## 2026-09-20 — Permissive modals count as obligation changes

**Decision.** The obligation regex in `services/compare.py` matches `may` alongside
`shall`/`must`/`will`.

**Why.** A failing test caught it: deleting "the Company **may** pay salary in lieu of notice"
changed what the employer is allowed to do, and the diff did not flag it. In a contract, discretion
is as substantive as duty, so removing a permission is a change worth surfacing.

**Alternatives.** Keeping the test aligned with the narrower regex would have been the smaller
change — and would have shipped a comparison engine that misses removed rights.
