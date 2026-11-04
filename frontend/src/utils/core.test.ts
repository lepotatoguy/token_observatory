import { describe, it, expect, beforeEach, vi } from "vitest";
import { compact, eventTotal, sum } from "./tokens";
import { relative, dayStart, dayKey, shiftDay } from "./time";
import { groupConversations, scoped } from "./conversations";
import { eventPricing, costOf } from "./cost";
import { csv } from "./export";
import { saved } from "./storage";
import { chat, now } from "../test/fixtures";
import type { Pricing } from "../types/snapshot";
describe("recorded tokens", () => {
  it.each([
    [0, "0"],
    [999, "999"],
    [1000, "1.0k"],
    [1000000, "1.00M"],
    [1000000000, "1.00B"],
  ])("compact %s", (n, value) => expect(compact(n as number)).toBe(value));
  it("never counts reasoning twice", () =>
    expect(eventTotal({ at: null, input: 2, output: 8, reasoning: 7 })).toBe(
      10,
    ));
});
describe("time", () => {
  it("handles absent, future, minute and hour timestamps", () => {
    expect(relative(null, now)).toBe("Undated");
    expect(relative(now + 60, now)).toBe("Just now");
    expect(relative(now - 60, now)).toBe("1m ago");
    expect(relative(now - 3600, now)).toBe("1h ago");
  });
  it("shifts local calendar dates", () =>
    expect(dayKey(dayStart(shiftDay("2024-12-31", 1)))).toBe("2025-01-01"));
});
describe("conversations", () => {
  it("joins child usage to root while preserving lifetime counters", () => {
    const root = chat({ totals: { ...sum([]), total: 9000, input: 9000 } }),
      child = chat({
        id: "child",
        session_id: "child",
        conversation_id: "root",
        subagent: true,
      });
    const grouped = groupConversations([root, child]);
    expect(grouped).toHaveLength(1);
    expect(grouped[0].agent_count).toBe(1);
    expect(grouped[0].events).toHaveLength(2);
    expect(grouped[0].totals.total).toBe(11000);
  });
  it("keeps provider identity distinct and honors subagent exclusion", () => {
    expect(
      groupConversations([chat(), chat({ provider: "codex" })]),
    ).toHaveLength(2);
    expect(
      scoped([chat({ subagent: true })], {
        provider: "all",
        agentsIncluded: false,
        range: "all",
        day: null,
        now,
      }),
    ).toHaveLength(0);
  });
  it("applies local day boundaries and excludes undated events from ranges", () => {
    const day = "2024-10-01",
      start = dayStart(day),
      events = [
        { at: null, input: 8 },
        { at: start - 1, input: 2 },
        { at: start, input: 4 },
        { at: dayStart(shiftDay(day, 1)), input: 16 },
      ];
    const rows = scoped([chat({ events })], {
      provider: "all",
      agentsIncluded: true,
      range: "all",
      day,
      now,
    });
    expect(rows[0].scope.total).toBe(4);
    expect(
      scoped([chat({ events })], {
        provider: "all",
        agentsIncluded: true,
        range: "all",
        day: null,
        now,
      })[0].scope.total,
    ).toBe(30);
  });
});
describe("published costs", () => {
  const prices: Pricing = {
    models: [{ match: "test", rates: [2, null, null, 0.2, 8] }],
  };
  it("retains priced components and flags missing cache-write cost", () => {
    const priced = eventPricing(
      { at: now, input: 1e6, write: 100, output: 1e6 },
      "test",
      "claude",
      prices,
    );
    expect(priced.cost).toBe(10);
    expect(priced.unreported).toBe(true);
    expect(priced.pricedTokens).toBe(2e6);
  });
  it("local providers remain zero-cost even with cloud model names", () => {
    const p = eventPricing({ at: now, input: 1e6 }, "test", "lmstudio", prices);
    expect(p).toMatchObject({ cost: 0, local: true, unreported: false });
    expect(costOf([chat({ provider: "ollama" })], prices).unpriced).toEqual([]);
  });
  it("uses the model-specific long-context threshold and 1h cache rate", () => {
    expect(
      eventPricing(
        { at: now, input: 11, write: 10, write_1h: 4 },
        "test",
        "claude",
        {
          models: [
            {
              match: "test",
              rates: [1, 2, 3, 4, 5],
              long_prompt: 10,
              long_rates: [10, 20, 30, 40, 50],
            },
          ],
        },
      ).cost,
    ).toBeCloseTo(0.00035);
  });
  it("unpriced models do not acquire fabricated rates", () =>
    expect(
      eventPricing({ at: now, input: 9 }, "unknown", "codex", prices),
    ).toMatchObject({ cost: 0, unreported: true, pricedTokens: 0 }));
});
describe("export and preference resilience", () => {
  beforeEach(() => localStorage.clear());
  it("escapes quotes and newlines in CSV", () =>
    expect(csv([chat({ title: 'A,"B"\nC' })])).toContain('"A,""B""\nC"'));
  it("retains preferences when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    saved.set("budget-test", 123);
    expect(saved.get("budget-test", 0)).toBe(123);
  });
});
