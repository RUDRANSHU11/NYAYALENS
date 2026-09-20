interface Props {
  id: string;
  label: string;
  hint?: string;
  onChange: (file: File | null) => void;
}

/** A labelled file input. Native on purpose: it is keyboard- and
 *  screen-reader-accessible without any extra work. */
export default function FileField({ id, label, hint, onChange }: Props) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium text-slate-800">
        {label}
      </label>
      <input
        id={id}
        name={id}
        type="file"
        accept=".pdf,.docx,.txt"
        aria-describedby={hint ? `${id}-hint` : undefined}
        onChange={(event) => onChange(event.target.files?.[0] ?? null)}
        className="rounded-lg border border-slate-300 bg-white p-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-brand-50 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-brand-700"
      />
      {hint && (
        <p id={`${id}-hint`} className="text-xs text-slate-600">
          {hint}
        </p>
      )}
    </div>
  );
}
