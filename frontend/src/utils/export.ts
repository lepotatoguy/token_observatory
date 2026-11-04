import type { ScopedSession } from "../types/session";
import type { Snapshot } from "../types/snapshot";
import { fields } from "./tokens";
import { cutoff, dayStart, shiftDay } from "./time";
export function download(name: string, type: string, content: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
export function buildCsvRows(sessions: ScopedSession[]) {
  return [
    [
      "provider",
      "title",
      "session_id",
      "model",
      "input",
      "cached",
      "write",
      "output",
      "reasoning",
      "total",
      "last_activity",
    ],
    ...sessions.map((s) => [
      s.provider,
      s.title,
      s.session_id,
      s.model,
      ...([...fields, "reasoning", "total"] as const).map((key) =>
        s.usage_source === "unavailable" ||
        (s.cache_unreported && (key === "cached" || key === "write"))
          ? ""
          : s.scope[key],
      ),
      s.last ? new Date(s.last * 1000).toISOString() : "",
    ]),
  ];
}
export function csv(sessions: ScopedSession[]) {
  const quote = (value: unknown) => {
    let text = String(value ?? "");
    if (/^[=+@\-\t\r\n]/.test(text)) text = "'" + text;
    return '"' + text.replaceAll('"', '""') + '"';
  };
  return (
    "\ufeff" +
    buildCsvRows(sessions)
      .map((row) => row.map(quote).join(","))
      .join("\r\n")
  );
}
export interface ExportFilters {
  provider: string;
  range: string;
  day: string | null;
  agentsIncluded: boolean;
  search: string;
  historyDay: string;
  now: number;
}
export function buildJsonPayload(
  snapshot: Snapshot,
  sessions: ScopedSession[],
  filters: ExportFilters,
) {
  return {
    schema_version: 1,
    accounting_version: snapshot.accounting_version || 1,
    exported_at: new Date().toISOString(),
    snapshot_at: new Date(snapshot.at * 1000).toISOString(),
    filters: {
      provider: filters.provider,
      range: filters.range,
      day: filters.day,
      since: cutoff(filters.range, filters.day, filters.now) || null,
      until: filters.day ? dayStart(shiftDay(filters.day, 1)) : null,
      include_subagents: filters.agentsIncluded,
      search: filters.search,
      saved_day: filters.historyDay || null,
    },
    sessions: sessions.map(({ scope, ...session }) => ({
      ...session,
      filtered_totals: scope,
    })),
    sources: snapshot.sources,
    warnings: snapshot.warnings,
  };
}
