import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LimitsPanel } from "./LimitsPanel";
import { suggestedBudget, BudgetPanel } from "./BudgetPanel";
import { useAppStore } from "../../store/useAppStore";
import { chat, snapshot, now } from "../../test/fixtures";
import { api } from "../../api/client";
beforeEach(() => {
  localStorage.clear();
  useAppStore.setState({ historyDay: "" });
});
describe("quota and budget meters", () => {
  it("shows MiniMax quotas and uses its weekly quota for the suggested budget", () => {
    const s = snapshot({
      providers: { enabled: ["minimax"], setup_done: true },
      sessions: [chat({ provider: "minimax", events: [{ at: now - 60, input: 1100 }] })],
      limits: { minimax: { source: "live", observed_at: now,
        primary: { window_minutes: 300, used_percent: 3, resets_at: now + 3600 },
        secondary: { window_minutes: 10080, used_percent: 11, resets_at: now + 2 * 86400 } } }
    });
    render(<LimitsPanel snapshot={s} now={now} />);
    expect(screen.getByRole("progressbar", { name: "MiniMax 5-hour quota" })).toHaveAttribute("aria-valuenow", "3");
    expect(screen.getByRole("progressbar", { name: "MiniMax Weekly quota" })).toHaveAttribute("aria-valuenow", "11");
    expect(screen.getByText(/Checked with MiniMax/)).toBeInTheDocument();
    expect(suggestedBudget(s, now)).toEqual({ parts: [{ provider: "minimax", daily: 4450, estimated: false }], missing: [], total: 4450 });
  });
  it("explains missing MiniMax credentials and failed refreshes", () => {
    render(<LimitsPanel snapshot={snapshot({ providers: { enabled: ["minimax"], setup_done: true },
      live_limits: { checked_at: now, errors: { minimax: "Quota check failed" } } })} now={now} />);
    expect(screen.getByText(/Sign in to MiniMax Code or add a Coding Plan API key/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("MiniMax: Quota check failed");
  });
  it("shows accurate quota bars with capped width", () => {
    render(
      <LimitsPanel
        snapshot={snapshot({
          limits: {
            claude: {
              primary: {
                window_minutes: 300,
                used_percent: 42,
                resets_at: now + 3600,
              },
              secondary: {
                window_minutes: 10080,
                used_percent: 101,
                resets_at: now + 86400,
              },
            },
          },
        })}
        now={now}
      />,
    );
    const bars = screen.getAllByRole("progressbar");
    expect(bars[0]).toHaveAttribute("aria-valuenow", "42");
    expect(bars[0].firstChild).toHaveStyle({ width: "42%" });
    expect(bars[1].firstChild).toHaveStyle({ width: "100%" });
  });
  it("sizes provider zones by suggested shares and marks exceeded provider shares", () => {
    const s = snapshot({
      sessions: [
        chat({ provider: "claude", events: [{ at: now - 60, input: 1000 }] }),
        chat({ provider: "codex", events: [{ at: now - 60, input: 3000 }] }),
      ],
      limits: {
        claude: {
          observed_at: now,
          secondary: {
            window_minutes: 10080,
            used_percent: 50,
            resets_at: now + 86400,
          },
        },
        codex: {
          observed_at: now,
          secondary: {
            window_minutes: 10080,
            used_percent: 50,
            resets_at: now + 86400,
          },
        },
      },
    });
    localStorage.setItem("to.dailyBudget", "2000");
    render(<BudgetPanel snapshot={s} now={now} />);
    expect(screen.getByTestId("budget-zone-claude")).toHaveStyle({
      flexGrow: "500",
    });
    expect(screen.getByTestId("budget-zone-codex")).toHaveStyle({
      flexGrow: "1500",
    });
    expect(screen.getByTestId("budget-zone-claude")).toHaveClass("critical");
    expect(screen.getByText("200%")).toBeInTheDocument();
  });
});

describe("forecast budget", () => {
  afterEach(() => vi.restoreAllMocks());
  const two = () =>
    snapshot({
      sessions: [
        chat({ provider: "claude", events: [{ at: now - 60, input: 1000 }] }),
        chat({ provider: "codex", events: [{ at: now - 60, input: 3000 }] }),
      ],
      limits: {
        claude: { observed_at: now, secondary: { window_minutes: 10080, used_percent: 50, resets_at: now + 86400 } },
        codex: { observed_at: now, secondary: { window_minutes: 10080, used_percent: 50, resets_at: now + 86400 } },
      },
    });
  const part = (daily: number | null, extra = {}) => ({
    daily, share: 0.5, start_of_day_capacity: 1, remaining_capacity: 1, used_today: 0,
    demand_method: "flat" as const, calibration: "history" as const, calibration_pairs: 6, shrinkage: 0,
    backtest: { model_mae: 42500000, baseline_mae: 42500000, days: 16 } as { model_mae: number; baseline_mae: number; days: number } | null,
    confidence: "normal" as const, days_used: 22, estimated: false, warnings: [],
    excluded: null as "no_weekly_quota" | "insufficient_data" | null, ...extra,
  });
  const forecast = (providers: Record<string, ReturnType<typeof part>>) => ({
    date: "2026-11-05", generated_at: now, total: 0, warnings: [], providers,
  });
  it("uses forecast budgets for the split and the Use suggested button", async () => {
    vi.spyOn(api, "forecast").mockResolvedValue(forecast({ claude: part(5000), codex: part(3000) }));
    render(<BudgetPanel snapshot={two()} now={now} />);
    await waitFor(() => expect(screen.getByTestId("budget-zone-claude")).toHaveStyle({ flexGrow: "5000" }));
    expect(screen.getByTestId("budget-zone-codex")).toHaveStyle({ flexGrow: "3000" });
    expect(screen.getByText(/Forecast from your usage history/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Use suggested"));
    expect(localStorage.getItem("to.dailyBudget")).toBe("8000");
  });
  it("names the algorithm and its measured error for each forecast provider", async () => {
    vi.spyOn(api, "forecast").mockResolvedValue(forecast({
      claude: part(5000),
      codex: part(3000, { demand_method: "weekday_regression", shrinkage: 0.5, backtest: { model_mae: 1500000, baseline_mae: 2000000, days: 12 } }),
    }));
    render(<BudgetPanel snapshot={two()} now={now} />);
    await screen.findByText(/Claude Code: even split across the remaining days \(no weekday pattern beat the flat baseline\)/);
    expect(screen.getByText(/Claude Code:.*tokens per percent from 6 readings over 22 days; usage-prediction error 42\.5\d*M tokens a day over 16 test days \(flat baseline 42\.5\d*M\)\./)).toBeInTheDocument();
    expect(screen.getByText(/Codex: weekday regression \(shrinkage 0\.5\);.*error 1\.5\d*M tokens a day over 12 test days \(flat baseline 2\.0\d*M\)/)).toBeInTheDocument();
  });
  it("says so when accuracy has not been measured yet", async () => {
    vi.spyOn(api, "forecast").mockResolvedValue(forecast({ claude: part(5000, { backtest: null, days_used: 9 }), codex: part(3000) }));
    render(<BudgetPanel snapshot={two()} now={now} />);
    expect(await screen.findByText(/Claude Code: even split across the remaining days; tokens per percent from 6 readings over 9 days; accuracy not measured yet \(needs 18 days of history\)\./)).toBeInTheDocument();
  });
  it("labels a provider the forecast could not budget as an even split", async () => {
    vi.spyOn(api, "forecast").mockResolvedValue(
      forecast({ claude: part(5000), codex: part(null, { excluded: "insufficient_data" }) }),
    );
    render(<BudgetPanel snapshot={two()} now={now} />);
    await waitFor(() => expect(screen.getByTestId("budget-zone-claude")).toHaveStyle({ flexGrow: "5000" }));
    expect(screen.getByTestId("budget-zone-codex")).toHaveStyle({ flexGrow: "3000" });
    expect(screen.getByText(/Codex 3\.0k \(even split\)/)).toBeInTheDocument();
    expect(screen.queryByText(/^Codex:/)).not.toBeInTheDocument();
  });
  it("keeps today's suggestion when the forecast request fails", async () => {
    const spy = vi.spyOn(api, "forecast").mockRejectedValue(new Error("down"));
    render(<BudgetPanel snapshot={two()} now={now} />);
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(screen.getByTestId("budget-zone-claude")).toHaveStyle({ flexGrow: "1000" });
    expect(screen.getByTestId("budget-zone-codex")).toHaveStyle({ flexGrow: "3000" });
    expect(screen.getByText(/Estimated from quota snapshots and logged usage/)).toBeInTheDocument();
  });
  it("ignores the forecast while a past day is shown", async () => {
    useAppStore.setState({ historyDay: "2026-11-03" });
    const spy = vi.spyOn(api, "forecast").mockResolvedValue(forecast({ claude: part(5000), codex: part(3000) }));
    render(<BudgetPanel snapshot={two()} now={now} />);
    expect(spy).not.toHaveBeenCalled();
    expect(screen.getByTestId("budget-zone-claude")).toHaveStyle({ flexGrow: "1000" });
  });
});
