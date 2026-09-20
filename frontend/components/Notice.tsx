import type { ReactNode } from "react";

type Tone = "info" | "error";

const STYLES: Record<Tone, string> = {
  info: "border-brand-100 bg-brand-50 text-brand-900",
  error: "border-red-200 bg-red-50 text-red-900",
};

/** Short status message. Errors are announced immediately, info politely. */
export default function Notice({ tone = "info", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <p
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-lg border p-3 text-sm ${STYLES[tone]}`}
    >
      {children}
    </p>
  );
}
