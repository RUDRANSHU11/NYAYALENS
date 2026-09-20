import { useState, type FormEvent } from "react";

import { askDocument, type Answer, type Language } from "@/services/api";
import Notice from "./Notice";

/** Features 4 + 5: ask in plain language, get an answer backed by the clauses
 *  it came from. */
export default function AskPanel({
  documentId,
  language,
}: {
  documentId: string;
  language: Language;
}) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (question.trim().length < 3) {
      setError("Please write a slightly longer question.");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      setAnswer(await askDocument(documentId, question.trim(), language));
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Could not answer that.");
      setAnswer(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-labelledby="ask-heading"
      className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4"
    >
      <h2 id="ask-heading" className="text-lg font-semibold text-slate-900">
        Ask about this document
      </h2>

      <form onSubmit={onSubmit} className="flex flex-col gap-2">
        <label htmlFor="question" className="text-sm font-medium text-slate-800">
          Your question
        </label>
        <textarea
          id="question"
          name="question"
          rows={3}
          maxLength={1000}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          aria-describedby="question-hint"
          className="rounded-lg border border-slate-300 p-2 text-sm"
        />
        <p id="question-hint" className="text-xs text-slate-600">
          For example: “What happens if I terminate this agreement early?”
        </p>
        <button
          type="submit"
          disabled={busy}
          aria-busy={busy}
          className="self-start rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
        >
          {busy ? "Looking through the document…" : "Ask"}
        </button>
      </form>

      {error && <Notice tone="error">{error}</Notice>}

      <div aria-live="polite" className="flex flex-col gap-3">
        {answer && (
          <>
            {answer.notice && <Notice>{answer.notice}</Notice>}
            {answer.answer && (
              <div lang={language} className="rounded-lg bg-brand-50 p-3">
                <h3 className="text-sm font-semibold text-brand-900">Answer</h3>
                <p className="mt-1 text-sm text-slate-800">{answer.answer}</p>
                {!answer.grounded && (
                  <p className="mt-2 text-sm font-medium text-amber-900">
                    This document does not appear to cover that directly.
                  </p>
                )}
              </div>
            )}

            <div>
              <h3 className="text-sm font-semibold text-slate-900">
                Where this comes from
              </h3>
              <ol className="mt-2 flex flex-col gap-2">
                {answer.sources.map((source) => (
                  <li
                    key={source.chunk_id}
                    className="rounded-lg border border-slate-200 p-3 text-sm"
                  >
                    <p className="font-medium text-brand-900">
                      {source.reference}
                      {source.cited && (
                        <span className="ml-2 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-900">
                          used in the answer
                        </span>
                      )}
                    </p>
                    <p className="mt-1 text-slate-800">{source.text}</p>
                  </li>
                ))}
              </ol>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
