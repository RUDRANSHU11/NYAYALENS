import { useState, type FormEvent } from "react";

import DiffText from "@/components/DiffText";
import FileField from "@/components/FileField";
import Layout from "@/components/Layout";
import Notice from "@/components/Notice";
import { compareDocuments, type Comparison, type Language } from "@/services/api";

const KIND_STYLES: Record<string, string> = {
  added: "bg-green-100 text-green-900",
  removed: "bg-red-100 text-red-900",
  modified: "bg-amber-100 text-amber-900",
};

export default function ComparePage() {
  const [language, setLanguage] = useState<Language>("en");
  const [before, setBefore] = useState<File | null>(null);
  const [after, setAfter] = useState<File | null>(null);
  const [result, setResult] = useState<Comparison | null>(null);
  const [onlySignificant, setOnlySignificant] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!before || !after) {
      setError("Choose both versions of the contract.");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      setResult(await compareDocuments(before, after, language));
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Could not compare those documents.");
    } finally {
      setBusy(false);
    }
  }

  const changes = result
    ? result.changes.filter((change) => !onlySignificant || change.significant)
    : [];

  return (
    <Layout title="Compare two versions" language={language} onLanguageChange={setLanguage}>
      <div className="flex flex-col gap-6">
        <section
          aria-labelledby="compare-heading"
          className="rounded-xl border border-slate-200 bg-white p-4"
        >
          <h1 id="compare-heading" className="text-xl font-semibold text-slate-900">
            Compare two versions of a contract
          </h1>
          <p className="mt-1 text-sm text-slate-700">
            NyayaLens lines the two versions up clause by clause and shows what was added, removed
            or changed — including amounts, dates, notice periods and obligations.
          </p>

          <form onSubmit={onSubmit} className="mt-4 flex flex-wrap items-end gap-4">
            <FileField id="file-a" label="Older version" onChange={setBefore} />
            <FileField id="file-b" label="Newer version" onChange={setAfter} />
            <button
              type="submit"
              disabled={busy}
              aria-busy={busy}
              className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
            >
              {busy ? "Comparing…" : "Compare versions"}
            </button>
          </form>

          <div aria-live="polite" className="mt-3 empty:mt-0">
            {error && <Notice tone="error">{error}</Notice>}
          </div>
        </section>

        <div aria-live="polite">
          {result && (
            <section aria-labelledby="result-heading" className="flex flex-col gap-4">
              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <h2 id="result-heading" className="text-lg font-semibold text-slate-900">
                  {result.name_before} → {result.name_after}
                </h2>
                <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm text-slate-700">
                  {(
                    [
                      ["Added", result.added],
                      ["Removed", result.removed],
                      ["Modified", result.modified],
                      ["Unchanged", result.unchanged],
                    ] as const
                  ).map(([label, count]) => (
                    <div key={label} className="flex gap-1">
                      <dt className="font-medium">{label}:</dt>
                      <dd>{count}</dd>
                    </div>
                  ))}
                </dl>

                <div className="mt-3 flex items-center gap-2">
                  <input
                    id="only-significant"
                    type="checkbox"
                    checked={onlySignificant}
                    onChange={(event) => setOnlySignificant(event.target.checked)}
                    className="h-4 w-4"
                  />
                  <label htmlFor="only-significant" className="text-sm text-slate-700">
                    Only changes that affect money, dates, obligations or key clauses
                  </label>
                </div>
              </div>

              {changes.length === 0 && (
                <Notice>
                  No differences to show. The two versions look the same on the points NyayaLens
                  checks.
                </Notice>
              )}

              <ol className="flex flex-col gap-3">
                {changes.map((change) => (
                  <li key={change.id}>
                    <article
                      aria-labelledby={`change-${change.id}`}
                      className="lazy-card rounded-xl border border-slate-200 bg-white p-4"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-semibold ${KIND_STYLES[change.kind]}`}
                        >
                          {change.kind}
                        </span>
                        <h3
                          id={`change-${change.id}`}
                          className="text-sm font-semibold text-brand-900"
                        >
                          {change.label}
                        </h3>
                        {change.obligation_changed && (
                          <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-800">
                            obligation changed
                          </span>
                        )}
                      </div>

                      {change.categories.length > 0 && (
                        <ul aria-label="Affected areas" className="mt-2 flex flex-wrap gap-1">
                          {change.categories.map((category) => (
                            <li
                              key={category}
                              className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900"
                            >
                              {category}
                            </li>
                          ))}
                        </ul>
                      )}

                      {change.values.length > 0 && (
                        <ul className="mt-3 flex flex-col gap-1 text-sm text-slate-800">
                          {change.values.map((value, index) => (
                            <li key={index}>
                              <span className="font-medium capitalize">{value.kind}:</span>{" "}
                              {value.before ?? "not present"}{" "}
                              <span aria-hidden="true">→</span>
                              <span className="sr-only">changed to</span> {value.after ?? "removed"}
                            </li>
                          ))}
                        </ul>
                      )}

                      {change.impact && (
                        <p
                          lang={language}
                          className="mt-3 rounded-lg bg-brand-50 p-3 text-sm text-slate-800"
                        >
                          <span className="font-semibold text-brand-900">What this means: </span>
                          {change.impact}
                        </p>
                      )}

                      <div className="mt-3">
                        <DiffText segments={change.diff} />
                      </div>
                    </article>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </div>
      </div>
    </Layout>
  );
}
