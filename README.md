# ⚖️ NyayaLens

**See the law clearly.**

NyayaLens is a GenAI-powered legal document assistant. Upload an agreement, and it marks the
clauses worth reading, explains them in plain language, answers questions about them, and shows
you exactly which clause and page each answer came from.

> Understand the document. Compare the changes. Find what matters.

**Live:** https://nyayalens-pied.vercel.app

---

## What it does

| # | Feature | Where it lives |
|---|---------|----------------|
| 1 | **Legal document simplification** — original clause and plain-language explanation side by side, with the obligations and rights it creates | [`analysis.explain_clause`](backend/services/analysis.py:37), [`ClauseList.tsx`](frontend/components/ClauseList.tsx) |
| 2 | **Contract comparison** — added, removed and modified clauses, plus changed amounts, dates, durations and obligations | [`compare.py`](backend/services/compare.py:106), [`compare.tsx`](frontend/pages/compare.tsx) |
| 3 | **Important clause detection** — 14 categories (termination, notice, penalties, confidentiality, IP, indemnity, liability, non-compete, …) with a note on why each matters | [`clauses.py`](backend/services/clauses.py) |
| 4 | **Ask questions** — natural-language questions answered from the document, with the clause and page used | [`ask_document`](backend/api/routes.py:110), [`AskPanel.tsx`](frontend/components/AskPanel.tsx) |
| 5 | **Evidence-based responses** — RAG: only retrieved clauses are sent to the model, and the answer cites them | [`store.search`](backend/rag/store.py:96), [`analysis.answer_question`](backend/services/analysis.py:63) |
| 6 | **Accessible legal language** — plain English or Hindi, keyboard- and screen-reader-friendly UI | language selector in [`Layout.tsx`](frontend/components/Layout.tsx) |

Everything except the generated text works **with no AI provider configured**: clause detection,
retrieval, comparison and source references are deterministic code, not model output.

---

## Architecture

```
        User
          │
   Next.js frontend (React + Tailwind)
          │  JSON / multipart over HTTP
   FastAPI backend
          ├── Document processing ── PyMuPDF / python-docx / OCR
          ├── RAG engine ─────────── fastembed (ONNX) → FAISS
          └── Comparison engine ──── difflib alignment + value extraction
          │
   GenAI model (any OpenAI-compatible provider)
          │
   Answer + explanation + source reference
```

### AI pipeline

| Step | What happens | Code |
|------|--------------|------|
| 1 | Upload validated (type, magic bytes, size, page count, zip expansion) | [`extract._validate`](backend/document_processing/extract.py:66) |
| 2 | Text + metadata extracted; scanned PDFs fall back to OCR via the model's vision capability | [`extract`](backend/document_processing/extract.py:56), [`analysis.ocr_pages`](backend/services/analysis.py:132) |
| 3 | Clause-aware chunking keeps page, section and clause number | [`chunk_document`](backend/document_processing/chunking.py:81) |
| 4 | Chunks embedded locally (no API key, no data sent out) | [`embed_documents`](backend/rag/embeddings.py:55) |
| 5 | Vectors indexed in FAISS, held in memory with a TTL | [`store.add`](backend/rag/store.py:48) |
| 6 | Question embedded and matched against the index | [`store.search`](backend/rag/store.py:96) |
| 7 | Retrieved clauses sent to the model as grounded context | [`analysis.answer_question`](backend/services/analysis.py:63) |
| 8 | Answer linked back to clause, section and page | `Chunk.reference` in [`chunking.py`](backend/document_processing/chunking.py:30) |

A deeper walkthrough of the code paths is in [flow.md](flow.md); the reasoning behind the
choices is in [decisions.md](decisions.md).

---

## Tech stack

- **Frontend:** Next.js 16 (Pages Router), React 19, TypeScript, Tailwind CSS 4
- **Backend:** Python 3.12, FastAPI, Pydantic
- **AI/ML:** any OpenAI-compatible LLM (Gemini by default), fastembed ONNX embeddings, FAISS, RAG
- **Document processing:** PyMuPDF, python-docx, model-vision OCR for scans
- **Deployment:** one Vercel project — Next.js and FastAPI as Vercel Services, same origin ([`vercel.json`](vercel.json))

---

## Run it

### Backend

```bash
python -m venv .venv && .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then put your key in LLM_API_KEY
uvicorn backend.main:app --reload --port 8000
```

API docs: <http://localhost:8000/docs>

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

App: <http://localhost:3000>

### Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

86 tests, no network calls: the suite pins hashing embeddings and stubs the model provider, so
every "no AI configured" branch is covered too.

---

## Configuration

Any OpenAI-compatible chat-completions endpoint works — Gemini, OpenAI, Groq, OpenRouter, or a
local Ollama — by changing three variables:

```env
LLM_API_KEY=...
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
LLM_MODEL=gemini-2.5-flash
```

Limits worth knowing (all in `.env.example`): `MAX_UPLOAD_MB=10`, `MAX_PAGES=120`,
`DOC_TTL_MINUTES=30`, `RATE_LIMIT_PER_MINUTE=30`.

---

## Efficiency

- **Non-blocking by default.** Handlers are async, so a model round trip (seconds) never holds a
  worker thread; parsing, chunking, embedding and diffing are pushed to the threadpool so they
  never block the event loop. Scanned pages and the two sides of a comparison run concurrently.
- **Nothing loads until it is needed.** PDF/DOCX parsers and the embedding model load lazily, the
  health check never triggers a model download, and the model is baked into the build so cold
  instances do not fetch ~70 MB before their first answer.
- **Indexing is paid once.** Chunks are embedded locally at upload (no per-request API cost) and
  searched with exact FAISS inner product; clause flags are computed once and stored; clause
  lookups by id are O(1).
- **The model is called sparingly.** Only retrieved clauses are sent. Explanations and answers are
  cached per document and language (answers bounded to 100), all change impacts go out in one
  batched call, and scanned pages are OCR'd concurrently (4 at a time) instead of one by one.
- **Bounded work everywhere.** Upload size, page count, OCR pages, question length, comparison
  pairing (40×40) and documents in memory all have hard caps.
- **Small, fast responses.** JSON over 1 KB is gzip-compressed, both pages are statically
  prerendered, and long clause lists use `content-visibility: auto` so off-screen cards are not
  laid out.
- **Lean deploy.** Test tooling lives in `requirements-dev.txt`, not in the production bundle.

---

## Privacy & security

- Uploads are parsed **from memory** — no document is written to disk by the app.
- Documents live behind an unguessable id, expire after `DOC_TTL_MINUTES`, and can be deleted
  immediately from the UI. Nothing survives a restart.
- Embeddings are computed **locally**, so indexing never sends your document anywhere.
- Only the clauses needed to answer (and page images, if the file is a scan) reach the model.
- Uploads are checked by magic bytes, size, page count and zip expansion before parsing.
- The model key stays server-side; CORS is restricted; security headers are set on both tiers;
  per-IP rate limiting protects the model budget.
- Document text is untrusted input: it is fenced in prompts and the system prompt forbids acting
  on instructions found inside it.

---

## Disclaimer

NyayaLens is an **informational and educational tool**. It does not provide legal representation
and does not replace a qualified lawyer. AI-generated explanations may contain errors — consult a
qualified legal professional before acting on anything here, especially for contracts, disputes
or financial decisions.

---

## Sample documents

`data/sample_employment_v1.txt` and `data/sample_employment_v2.txt` are two versions of the same
employment agreement — upload the first to try explanations and questions, or both on the compare
page to see changed salary, probation, notice period and the new non-compete and penalty clauses.
