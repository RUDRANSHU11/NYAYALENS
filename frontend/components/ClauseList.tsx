import { useMemo, useState } from "react";

import {
  explainClause,
  type Clause,
  type DocumentPayload,
  type Explanation,
  type Language,
} from "@/services/api";
import Notice from "./Notice";

interface Props {
  document: DocumentPayload;
  language: Language;
}

/** Feature 1 + 3: the clause list, with important ones flagged and a
 *  plain-language explanation on request. */
export default function ClauseList({ document: doc, language }: Props) {
  const [filter, setFilter] = useState<"important" | "all">("important");
  const [explanations, setExplanations] = useState<Record<string, Explanation>>({});
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const important = useMemo(
    () => doc.clauses.filter((clause) => clause.categories.length > 0),
    [doc],
  );
  const visible = filter === "important" ? important : doc.clauses;
  const categoriesPresent = useMemo(
    () => Array.from(new Set(important.flatMap((clause) => clause.categories))).sort(),
    [important],
  );

  async function explain(clause: Clause) {
    const key = `${clause.id}:${language}`;
    if (explanations[key] || pending) return;

    setPending(clause.id);
    setError(null);
    try {
      const result = await explainClause(doc.id, clause.id, language);
      setExplanations((current) => ({ ...current, [key]: result }));
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Could not explain this clause.");
    } finally {
      setPending(null);
    }
  }

  return (
    <section aria-labelledby="clauses-heading" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="clauses-heading" className="text-lg font-semibold text-slate-900">
          Clauses
        </h2>
        <fieldset className="flex items-center gap-4">
          <legend className="sr-only">Which clauses to show</legend>
          {(
            [
              ["important", `Important (${important.length})`],
              ["all", `All (${doc.clauses.length})`],
            ] as const
          ).map(([value, label]) => (
            <span key={value} className="flex items-center gap-1.5">
              <input
                type="radio"
                id={`filter-${value}`}
                name="clause-filter"
                value={value}
                checked={filter === value}
                onChange={() => setFilter(value)}
                className="h-4 w-4"
              />
              <label htmlFor={`filter-${value}`} className="text-sm text-slate-700">
                {label}
              </label>
            </span>
          ))}
        </fieldset>
      </div>

      {categoriesPresent.length > 0 && (
        <details className="rounded-xl border border-slate-200 bg-white p-4">
          <summary className="cursor-pointer text-sm font-medium text-brand-700">
            Why these clauses matter
          </summary>
          <dl className="mt-3 space-y-2 text-sm">
            {categoriesPresent.map((category) => (
              <div key={category}>
                <dt className="font-medium text-slate-900">{category}</dt>
                <dd className="text-slate-700">{doc.category_notes[category]}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}

      {error && <Notice tone="error">{error}</Notice>}
      {visible.length === 0 && (
        <Notice>No clauses to show here. Switch to “All” to read the whole document.</Notice>
      )}

      <ol className="flex flex-col gap-3">
        {visible.map((clause) => {
          const explanation = explanations[`${clause.id}:${language}`];
          const busy = pending === clause.id;
          return (
            <li key={clause.id}>
              <article
                aria-labelledby={`clause-${clause.id}`}
                className="rounded-xl border border-slate-200 bg-white p-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <h3
                    id={`clause-${clause.id}`}
                    className="text-sm font-semibold text-brand-900"
                  >
                    {clause.reference}
                  </h3>
                  {clause.categories.length > 0 && (
                    <ul aria-label="Flagged as" className="flex flex-wrap gap-1">
                      {clause.categories.map((category) => (
                        <li
                          key={category}
                          className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900"
                        >
                          {category}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <p className="mt-2 text-sm leading-relaxed text-slate-800">{clause.text}</p>

                <button
                  type="button"
                  onClick={() => explain(clause)}
                  disabled={!doc.ai_enabled || busy || Boolean(explanation)}
                  aria-busy={busy}
                  className="mt-3 rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {busy ? "Explaining…" : "Explain in plain language"}
                </button>

                <div aria-live="polite">
                  {explanation && (
                    <div lang={language} className="mt-3 rounded-lg bg-brand-50 p-3 text-sm">
                      <h4 className="font-semibold text-brand-900">In plain language</h4>
                      <p className="mt-1 text-slate-800">{explanation.explanation}</p>
                      {(
                        [
                          ["What you must do", explanation.obligations],
                          ["What you are entitled to", explanation.rights],
                          ["Easy to miss", explanation.watch_out],
                        ] as const
                      )
                        .filter(([, items]) => items.length > 0)
                        .map(([title, items]) => (
                          <div key={title} className="mt-2">
                            <h5 className="font-medium text-slate-900">{title}</h5>
                            <ul className="ml-5 list-disc text-slate-800">
                              {items.map((item) => (
                                <li key={item}>{item}</li>
                              ))}
                            </ul>
                          </div>
                        ))}
                    </div>
                  )}
                </div>
              </article>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
