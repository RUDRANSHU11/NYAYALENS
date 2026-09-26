/** Typed client for the NyayaLens API. The browser never talks to a model
 *  provider directly - the API key stays on the server. */

// Deployed, the API is the same origin (Vercel routes /api/* to the backend
// service); in `next dev` it is the local FastAPI server.
const BASE = (
  process.env.NEXT_PUBLIC_API_URL ??
  (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "")
).replace(/\/$/, "");

export type Language = "en" | "hi";

export interface Clause {
  id: string;
  text: string;
  page: number | null;
  section: string | null;
  clause: string | null;
  reference: string;
  categories: string[];
}

export interface DocumentPayload {
  id: string;
  name: string;
  pages: number;
  chunk_count: number;
  important_count: number;
  ocr_used: boolean;
  expires_in: number;
  ai_enabled: boolean;
  clauses: Clause[];
  category_notes: Record<string, string>;
}

export interface Explanation {
  chunk_id: string;
  reference: string;
  original: string;
  explanation: string;
  obligations: string[];
  rights: string[];
  watch_out: string[];
  language: Language;
  ai_used: boolean;
}

export interface Source {
  chunk_id: string;
  reference: string;
  page: number | null;
  section: string | null;
  clause: string | null;
  text: string;
  score: number;
  cited: boolean;
}

export interface Answer {
  answer: string;
  grounded: boolean;
  ai_used: boolean;
  language: Language;
  sources: Source[];
  notice: string | null;
}

export interface Segment {
  op: "equal" | "added" | "removed";
  text: string;
}

export interface ValueChange {
  kind: string;
  before: string | null;
  after: string | null;
}

export interface Change {
  id: string;
  kind: "added" | "removed" | "modified";
  label: string;
  reference_before: string | null;
  reference_after: string | null;
  text_before: string | null;
  text_after: string | null;
  categories: string[];
  values: ValueChange[];
  diff: Segment[];
  obligation_changed: boolean;
  significant: boolean;
  impact: string | null;
}

export interface Comparison {
  name_before: string;
  name_after: string;
  added: number;
  removed: number;
  modified: number;
  unchanged: number;
  ai_used: boolean;
  language: Language;
  changes: Change[];
}

export interface Health {
  status: string;
  ai_enabled: boolean;
  model: string | null;
  embeddings: string;
  store: string;
  documents_stored: number;
  document_ttl_minutes: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new Error("Could not reach the NyayaLens server. Is the backend running?");
  }

  if (!response.ok) {
    let detail = `Something went wrong (HTTP ${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* keep the generic message */
    }
    throw new Error(detail);
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const getHealth = () => request<Health>("/api/health");

export function uploadDocument(file: File) {
  const body = new FormData();
  body.append("file", file);
  return request<DocumentPayload>("/api/documents", { method: "POST", body });
}

export const deleteDocument = (id: string) =>
  request<void>(`/api/documents/${id}`, { method: "DELETE" });

export const explainClause = (id: string, chunkId: string, language: Language) =>
  request<Explanation>(`/api/documents/${id}/clauses/${chunkId}/explain`, json({ language }));

export const askDocument = (id: string, question: string, language: Language) =>
  request<Answer>(`/api/documents/${id}/ask`, json({ question, language }));

export function compareDocuments(before: File, after: File, language: Language) {
  const body = new FormData();
  body.append("file_a", before);
  body.append("file_b", after);
  body.append("language", language);
  return request<Comparison>("/api/compare", { method: "POST", body });
}
