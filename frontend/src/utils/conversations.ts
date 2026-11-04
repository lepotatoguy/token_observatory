import type { Session, ScopedSession } from "../types/session";
import { sum } from "./tokens";
import { cutoff, dayStart, shiftDay } from "./time";
export function groupConversations(sessions: Session[]): Session[] {
  const groups = new Map<string, Session[]>();
  for (const s of sessions) {
    const key = `${s.provider}:${s.conversation_id || s.session_id}`;
    groups.set(key, [...(groups.get(key) || []), s]);
  }
  return [...groups.values()].map((members) => {
    const key = members[0].conversation_id || members[0].session_id,
      root =
        members.find((s) => s.session_id === key && !s.subagent) ||
        members.find((s) => !s.subagent) ||
        members[0],
      events = members
        .flatMap((s) => s.events)
        .sort((a, b) => (a.at || 0) - (b.at || 0));
    return {
      ...root,
      id: `${root.provider}-conversation:${key}`,
      session_id: key,
      events,
      totals: sum(members.map((s) => ({ ...s.totals, at: null }))),
      last:
        members.reduce((latest, s) => Math.max(latest, s.last || 0), 0) || null,
      modified: members.reduce(
        (latest, s) => Math.max(latest, s.modified || 0),
        0,
      ),
      models: [...new Set(members.flatMap((s) => s.models))],
      source_files: [
        ...new Set(members.flatMap((s) => s.source_files || [s.source])),
      ],
      thread_ids: members.map((s) => s.session_id),
      agent_count: members.filter((s) => s.subagent).length,
      compactions: members.reduce((n, s) => n + s.compactions, 0),
      usage_source: members.some((s) => s.usage_source !== "unavailable")
        ? root.usage_source === "unavailable"
          ? "subagent response usage"
          : root.usage_source
        : "unavailable",
    };
  });
}
export interface ScopeOptions {
  provider: string;
  agentsIncluded: boolean;
  range: string;
  day: string | null;
  now: number;
}
export function scoped(sessions: Session[], o: ScopeOptions): ScopedSession[] {
  const since = cutoff(o.range, o.day, o.now),
    until = o.day ? dayStart(shiftDay(o.day, 1)) : null;
  return groupConversations(
    sessions.filter(
      (s) =>
        (o.provider === "all" || s.provider === o.provider) &&
        (o.agentsIncluded || !s.subagent),
    ),
  )
    .map((s) => {
      const events = s.events.filter(
        (e) =>
          !since ||
          (e.at !== null && e.at >= since && (!until || e.at < until)),
      );
      return { ...s, events, scope: sum(events) };
    })
    .filter(
      (s) =>
        !since ||
        s.events.length ||
        (!until && s.last !== null && s.last >= since),
    );
}
export const contextPercent = (s: Session) =>
  s.capacity && s.context != null ? (100 * s.context) / s.capacity : null;
