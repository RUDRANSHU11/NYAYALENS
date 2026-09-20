import type { Segment } from "@/services/api";

/** Word-level diff. Uses <ins>/<del> with text labels, so the change is not
 *  carried by colour alone. */
export default function DiffText({ segments }: { segments: Segment[] }) {
  return (
    <p className="text-sm leading-relaxed text-slate-800">
      {segments.map((segment, index) => {
        if (segment.op === "added") {
          return (
            <ins key={index} className="rounded px-0.5">
              <span className="sr-only">added: </span>
              {segment.text}{" "}
            </ins>
          );
        }
        if (segment.op === "removed") {
          return (
            <del key={index} className="rounded px-0.5">
              <span className="sr-only">removed: </span>
              {segment.text}{" "}
            </del>
          );
        }
        return <span key={index}>{segment.text} </span>;
      })}
    </p>
  );
}
