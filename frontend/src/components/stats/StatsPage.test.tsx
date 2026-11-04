import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import StatsPage from "./StatsPage";
import type { ScopedSession } from "../../types/session";
import type { Snapshot } from "../../types/snapshot";
import { sum } from "../../utils/tokens";

describe("Stats page", () => {
  it("renders all retained panels with safe empty values", () => {
    const snapshot: Snapshot = {
      at: 1,
      sessions: [],
      sources: [],
      warnings: [],
    };
    const { container } = render(
      <StatsPage sessions={[]} snapshot={snapshot} now={1} />,
    );
    expect(container.querySelectorAll(".stats-panel")).toHaveLength(24);
    expect(
      screen.getByRole("heading", { name: "Model details" }),
    ).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/NaN|Infinity/);
  });
  it("renders model names as text and reports priced coverage", () => {
    const events = [
      {
        at: 1,
        input: 100,
        cached: 0,
        write: 0,
        output: 10,
        reasoning: 0,
        model: "<script>",
      },
    ];
    const sessions = [
      {
        id: "synthetic",
        session_id: "test",
        provider: "codex",
        title: "<project>",
        project: "<project>",
        model: "<script>",
        models: ["<script>"],
        events,
        scope: sum(events),
        totals: sum(events),
        compactions: 0,
        last: 1,
        modified: 1,
        source: "synthetic",
        usage_source: "response usage",
        reported_cost: null,
        parse_errors: 0,
        context: null,
        capacity: null,
      } satisfies ScopedSession,
    ];
    const snapshot: Snapshot = { at: 2, sessions, sources: [], warnings: [] };
    const { container } = render(
      <StatsPage
        sessions={sessions}
        snapshot={snapshot}
        now={2}
        prices={{ models: [{ match: "<script>", rates: [1, 1, 1, 1, 1] }] }}
      />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<script>");
    expect(container.textContent).toContain("100.0%");
    expect(container.textContent).not.toMatch(/NaN|Infinity/);
  });
});
