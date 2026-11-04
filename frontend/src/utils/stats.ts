import type { ScopedSession } from "../types/session";
import { eventTotal, providerName, sum } from "./tokens";
import { dayKey, shiftDay } from "./time";

export function statsQuantile(sorted: number[], p: number): number | null {
  if (!sorted.length) return null;
  const index = (sorted.length - 1) * p,
    low = Math.floor(index);
  return sorted[low] + (sorted[Math.ceil(index)] - sorted[low]) * (index - low);
}

export function statsSummary(values: number[]) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const deviation = Math.sqrt(
    values.reduce((n, v) => n + (v - mean) ** 2, 0) / values.length,
  );
  return {
    mean,
    deviation,
    min: sorted[0],
    max: sorted[sorted.length - 1],
    q1: statsQuantile(sorted, 0.25)!,
    median: statsQuantile(sorted, 0.5)!,
    q3: statsQuantile(sorted, 0.75)!,
    cv: mean ? deviation / mean : null,
  };
}

export interface DayStats {
  total: number;
  input: number;
  cached: number;
  write: number;
  output: number;
  count: number;
  cacheMissing: boolean;
}
const emptyDay = (): DayStats => ({
  total: 0,
  input: 0,
  cached: 0,
  write: 0,
  output: 0,
  count: 0,
  cacheMissing: false,
});

export function statsData(sessions: ScopedSession[]) {
  const events = sessions.flatMap((s) => s.events);
  const dated = events.filter(
    (e) => typeof e.at === "number" && Number.isFinite(e.at),
  );
  const sizes = events.map(eventTotal).sort((a, b) => a - b);
  const days = new Map<string, DayStats>(),
    providers = new Map<string, number>(),
    models = new Map<string, number>(),
    projects = new Map<string, number>();
  const hours: number[][] = Array.from({ length: 7 }, () =>
    Array<number>(24).fill(0),
  );
  const weekdays = Array<number>(7).fill(0),
    distribution = Array<number>(5).fill(0);
  const buckets = [0, 1000, 10000, 100000, 1000000, Infinity];
  for (const s of sessions)
    for (const e of s.events) {
      const total = eventTotal(e);
      for (const [map, key] of [
        [models, e.model || s.model || "Unreported"],
        [projects, s.project || "No project"],
        [providers, providerName(s.provider)],
      ] as const)
        map.set(key, (map.get(key) || 0) + total);
      const bucket = buckets.findIndex(
        (_, i) => i < 5 && total < buckets[i + 1],
      );
      distribution[bucket]++;
      if (typeof e.at !== "number" || !Number.isFinite(e.at)) continue;
      const d = new Date(e.at * 1000),
        weekday = (d.getDay() + 6) % 7,
        key = dayKey(e.at);
      const day = days.get(key) || emptyDay();
      for (const field of ["input", "cached", "write", "output"] as const)
        day[field] += e[field] || 0;
      day.total += total;
      day.count++;
      day.cacheMissing ||= Boolean(e.cache_unreported || s.cache_unreported);
      days.set(key, day);
      hours[weekday][d.getHours()] += total;
      weekdays[weekday] += total;
    }
  const chats = sessions
    .filter((s) => s.events.length && s.scope.total > 0)
    .sort((a, b) => b.scope.total - a.scope.total);
  const timeline: [string, DayStats][] = [];
  const keys = [...days.keys()].sort();
  if (keys.length)
    for (
      let key = keys[0];
      key <= keys[keys.length - 1];
      key = shiftDay(key, 1)
    )
      timeline.push([key, days.get(key) || emptyDay()]);
  return {
    events,
    dated,
    sizes,
    days,
    hours,
    weekdays,
    distribution,
    providers,
    models,
    projects,
    chats,
    timeline,
    totals: sum(events),
    median: statsQuantile(sizes, 0.5),
    p90: statsQuantile(sizes, 0.9),
    p99: statsQuantile(sizes, 0.99),
    cacheMissing: sessions.some(
      (s) => s.cache_unreported || s.events.some((e) => e.cache_unreported),
    ),
  };
}
