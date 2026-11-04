import { describe, it, expect } from "vitest";
import { statsData, statsQuantile, statsSummary } from "./stats";
import type { ScopedSession } from "../types/session";
import { sum } from "./tokens";

describe("statistics", () => {
  it("uses interpolated quantiles and population dispersion", () => {
    expect(statsQuantile([], 0.5)).toBeNull();
    expect(statsQuantile([10, 110, 1000], 0.9)).toBe(822);
    const s = statsSummary([10, 20, 30])!;
    expect(s.median).toBe(20);
    expect(s.q1).toBe(15);
    expect(s.q3).toBe(25);
    expect(s.deviation).toBeCloseTo(Math.sqrt(200 / 3));
    expect(statsSummary([0, 0])!.cv).toBeNull();
  });
  it("excludes undated events from time charts and keeps missing-cache evidence", () => {
    const at = new Date(2026, 10, 2, 12).getTime() / 1000;
    const events = [
      { at, input: 80, cached: 20, output: 10, reasoning: 4, model: "first" },
      { at: at + 86400, input: 1000, model: "second", cache_unreported: true },
      { at: null, input: 10 },
    ];
    const session = {
      id: "synthetic",
      provider: "codex",
      project: "test",
      model: "fallback",
      events,
      scope: sum(events),
    } as ScopedSession;
    const d = statsData([session]);
    expect(d.totals.total).toBe(1120);
    expect(d.p90).toBe(822);
    expect(d.dated).toHaveLength(2);
    expect(d.days.size).toBe(2);
    expect(d.hours.flat().reduce((a, b) => a + b, 0)).toBe(1110);
    expect(d.models.get("fallback")).toBe(10);
    expect(d.distribution.slice(0, 2)).toEqual([2, 1]);
    expect(d.cacheMissing).toBe(true);
  });
});
