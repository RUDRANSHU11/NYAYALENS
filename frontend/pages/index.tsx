import { useEffect, useRef, useState, type FormEvent } from "react";

import AskPanel from "@/components/AskPanel";
import ClauseList from "@/components/ClauseList";
import FileField from "@/components/FileField";
import Layout from "@/components/Layout";
import Notice from "@/components/Notice";
import { deleteDocument, uploadDocument, type DocumentPayload, type Language } from "@/services/api";

export default function HomePage() {
  const [language, setLanguage] = useState<Language>("en");
  const [file, setFile] = useState<File | null>(null);
  const [doc, setDoc] = useState<DocumentPayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const summaryHeading = useRef<HTMLHeadingElement>(null);

  // Move focus to the results once a document is ready, so keyboard and screen
  // reader users are not left at the top of the page.
  useEffect(() => {
    if (doc) summaryHeading.current?.focus();
  }, [doc]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("Choose a PDF, DOCX or TXT file first.");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      setDoc(await uploadDocument(file));
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Could not read that document.");
    } finally {
      setBusy(false);
    }
  }

  async function removeDocument() {
    if (!doc) return;
    try {
      await deleteDocument(doc.id);
    } finally {
      setDoc(null);
      setFile(null);
    }
  }

  return (
    <Layout title="Understand a document" language={language} onLanguageChange={setLanguage}>
      <div className="flex flex-col gap-6">
        <section
          aria-labelledby="upload-heading"
          className="rounded-xl border border-slate-200 bg-white p-4"
        >
          <h1 id="upload-heading" className="text-xl font-semibold text-slate-900">
            Understand your legal document
          </h1>
          <p className="mt-1 text-sm text-slate-700">
            Upload an agreement, policy or contract. NyayaLens marks the clauses worth reading,
            explains them in plain language, and answers questions with the clause and page it used.
          </p>

          <form onSubmit={onSubmit} className="mt-4 flex flex-wrap items-end gap-3">
            <FileField
              id="document"
              label="Legal document"
              hint="PDF, DOCX or TXT, up to 10 MB. Scanned PDFs are read with OCR."
              onChange={setFile}
            />
            <button
              type="submit"
              disabled={busy}
              aria-busy={busy}
              className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
            >
              {busy ? "Reading the document…" : "Analyse document"}
            </button>
          </form>

          <div aria-live="polite" className="mt-3 empty:mt-0">
            {error && <Notice tone="error">{error}</Notice>}
          </div>
        </section>

        {doc && (
          <>
            <section
              aria-labelledby="summary-heading"
              className="rounded-xl border border-slate-200 bg-white p-4"
            >
              <h2
                id="summary-heading"
                ref={summaryHeading}
                tabIndex={-1}
                className="text-lg font-semibold text-slate-900"
              >
                {doc.name}
              </h2>
              <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm text-slate-700">
                <div className="flex gap-1">
                  <dt className="font-medium">Clauses:</dt>
                  <dd>{doc.chunk_count}</dd>
                </div>
                <div className="flex gap-1">
                  <dt className="font-medium">Worth attention:</dt>
                  <dd>{doc.important_count}</dd>
                </div>
                {doc.pages > 0 && (
                  <div className="flex gap-1">
                    <dt className="font-medium">Pages:</dt>
                    <dd>{doc.pages}</dd>
                  </div>
                )}
                <div className="flex gap-1">
                  <dt className="font-medium">Kept on the server for:</dt>
                  <dd>about {Math.round(doc.expires_in / 60)} minutes</dd>
                </div>
              </dl>

              {doc.ocr_used && (
                <p className="mt-2 text-sm text-slate-700">
                  This document had no text layer, so its pages were read with OCR. Check anything
                  that looks garbled against the original.
                </p>
              )}

              {!doc.ai_enabled && (
                <div className="mt-3">
                  <Notice>
                    No AI provider is configured on the server, so plain-language explanations are
                    unavailable. Clause detection, search and comparison still work.
                  </Notice>
                </div>
              )}

              <button
                type="button"
                onClick={removeDocument}
                className="mt-3 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-50"
              >
                Remove document
              </button>
            </section>

            <div className="grid gap-6 lg:grid-cols-[3fr_2fr] lg:items-start">
              <ClauseList document={doc} language={language} />
              <AskPanel documentId={doc.id} language={language} />
            </div>
          </>
        )}
      </div>
    </Layout>
  );
}
