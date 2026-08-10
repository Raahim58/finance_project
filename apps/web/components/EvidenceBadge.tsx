export function EvidenceBadge({ asOf, source, warning }: { asOf?: string | null; source?: string | null; warning?: string | null }) {
  return <div className={`rounded-md border px-3 py-2 text-xs ${warning ? "border-amber-300 bg-amber-50 text-amber-900" : "border-line bg-white text-muted"}`}>{warning ?? `As of ${asOf ?? "unavailable"} · ${source ?? "source unavailable"}`}</div>;
}
