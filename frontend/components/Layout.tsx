import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import type { ReactNode } from "react";

import type { Language } from "@/services/api";

const NAV = [
  { href: "/", label: "Understand & ask" },
  { href: "/compare", label: "Compare versions" },
];

interface Props {
  title: string;
  children: ReactNode;
  language: Language;
  onLanguageChange: (language: Language) => void;
}

export default function Layout({ title, children, language, onLanguageChange }: Props) {
  const { pathname } = useRouter();

  return (
    <>
      <Head>
        <title>{`${title} · NyayaLens`}</title>
        <meta
          name="description"
          content="NyayaLens explains legal documents in plain language and keeps the original clause, page and section reference next to every answer."
        />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>

      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:shadow-lg"
      >
        Skip to main content
      </a>

      <div className="mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-6 px-4 py-6">
        <header>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-2xl font-semibold tracking-tight text-brand-900">
                <span aria-hidden="true">⚖️ </span>NyayaLens
              </p>
              <p className="text-sm text-slate-600">See the law clearly.</p>
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="language" className="text-sm font-medium text-slate-700">
                Explanation language
              </label>
              <select
                id="language"
                name="language"
                value={language}
                onChange={(event) => onLanguageChange(event.target.value as Language)}
                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              >
                <option value="en">English</option>
                <option value="hi">हिन्दी (Hindi)</option>
              </select>
            </div>
          </div>

          <nav aria-label="Main" className="mt-5">
            <ul className="flex flex-wrap gap-2">
              {NAV.map((item) => {
                const active = pathname === item.href;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      className={`inline-block rounded-lg px-4 py-2 text-sm font-medium ${
                        active
                          ? "bg-brand-600 text-white"
                          : "bg-white text-brand-700 ring-1 ring-slate-200 hover:bg-brand-50"
                      }`}
                    >
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
        </header>

        <main id="main" className="flex-1">
          {children}
        </main>

        <footer className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-700">
          <h2 className="sr-only">Disclaimer and privacy</h2>
          <p>
            <strong>Not legal advice.</strong> NyayaLens is an informational and educational tool.
            It does not replace a qualified lawyer, and AI-generated explanations can be wrong —
            check anything important with a legal professional before you act on it.
          </p>
          <p className="mt-2">
            <strong>Your document.</strong> It is processed in memory, never saved to disk, and
            dropped automatically after a short time — or immediately when you select{" "}
            <em>Remove document</em>. Only the clauses needed to answer you (and page images, if the
            file is a scan) are sent to the configured AI provider.
          </p>
        </footer>
      </div>
    </>
  );
}
