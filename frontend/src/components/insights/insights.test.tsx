import { beforeEach, describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { LimitsPanel } from "./LimitsPanel";
import { suggestedBudget, BudgetPanel } from "./BudgetPanel";
import { useAppStore } from "../../store/useAppStore";
import { chat, snapshot, now } from "../../test/fixtures";
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
