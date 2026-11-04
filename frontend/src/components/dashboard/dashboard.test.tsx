import { beforeEach, describe, it, expect } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { MetricsBar } from "./MetricsBar";
import { ConversationTable } from "./ConversationTable";
import { Inspector } from "./Inspector";
import { ActivityChart, activityBounds } from "./ActivityChart";
import { useAppStore } from "../../store/useAppStore";
import { chat, now } from "../../test/fixtures";
beforeEach(() =>
  useAppStore.setState({
    search: "",
    selected: null,
    sort: "recent",
    sortDirection: "desc",
    range: "all",
    day: null,
  }),
);
describe("dashboard", () => {
  it("keeps the recorded model flag distinct from logged window capacity", () => {
    render(
      <Inspector
        session={chat({ capacity_source: "model ID [1m]" })}
        sessions={[chat()]}
        now={now}
      />,
    );
    expect(screen.getByText(/model ID \[1m\]/)).toBeInTheDocument();
    expect(screen.queryByText(/logged capacity/)).not.toBeInTheDocument();
  });
  it("handles 200000 recorded events without argument-spread overflow", () => {
    const events = Array.from({ length: 200000 }, (_, i) => ({
      at: now - i,
      input: 1,
    }));
    expect(activityBounds(events, now)).toEqual({
      start: now - 199999,
      end: now,
    });
  });
  it("shows actual token counts, cache share, and reasoning subset", () => {
    render(<MetricsBar sessions={[chat()]} />);
    expect(screen.getByText("2.0k")).toBeInTheDocument();
    expect(screen.getByText("1.6k")).toBeInTheDocument();
    expect(screen.getByText("31.3%")).toBeInTheDocument();
    expect(
      screen.getByText("80 recorded reasoning tokens included"),
    ).toBeInTheDocument();
  });
  it("marks partial known cost with an asterisk", () => {
    render(
      <MetricsBar
        sessions={[chat()]}
        pricing={{
          models: [{ match: "test", rates: [1, null, null, 0.1, 2] }],
        }}
      />,
    );
    expect(screen.getByText("$0.00*")).toBeInTheDocument();
    expect(
      screen.getByText("1 models have unreported cost components"),
    ).toBeInTheDocument();
  });
  it("searches and reverses token sort and supports keyboard row selection", () => {
    const rows = [
      chat(),
      chat({
        id: "beta",
        session_id: "beta",
        title: "Beta chat",
        last: now,
        scope: {
          input: 4,
          cached: 0,
          write: 0,
          output: 0,
          reasoning: 0,
          total: 4,
        },
      }),
    ];
    render(<ConversationTable sessions={rows} now={now} />);
    const tbody = screen.getAllByRole("rowgroup")[1];
    expect(within(tbody).getAllByRole("row")[0]).toHaveTextContent("Beta chat");
    fireEvent.click(screen.getByRole("button", { name: "Tokens" }));
    expect(within(tbody).getAllByRole("row")[0]).toHaveTextContent(
      "Alpha chat",
    );
    fireEvent.click(screen.getByRole("button", { name: "Tokens ↓" }));
    expect(within(tbody).getAllByRole("row")[0]).toHaveTextContent("Beta chat");
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "Alpha" },
    });
    expect(screen.queryByText("Beta chat")).not.toBeInTheDocument();
    fireEvent.keyDown(within(tbody).getAllByRole("row")[0], { key: "Enter" });
    expect(useAppStore.getState().selected).toBe("claude-1");
  });
  it("provides combined inspector and per-conversation context", () => {
    const { rerender } = render(<Inspector sessions={[chat()]} now={now} />);
    expect(
      screen.getByText("Context windows are per conversation"),
    ).toBeInTheDocument();
    rerender(<Inspector session={chat()} sessions={[chat()]} now={now} />);
    expect(screen.getByText("20.0%")).toBeInTheDocument();
    expect(screen.getByText("Recent usage updates")).toBeInTheDocument();
  });
  it("day bars are keyboard accessible and select a day filter", () => {
    render(
      <ActivityChart
        events={[{ at: now - 4 * 86400, input: 100 }]}
        now={now}
      />,
    );
    const bars = screen.getAllByRole("button");
    fireEvent.keyDown(bars[0], { key: "Enter" });
    expect(useAppStore.getState().day).not.toBeNull();
  });
});
