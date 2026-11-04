import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Header, PageHeading, FilterBar } from "./Header";
import { useAppStore } from "../../store/useAppStore";
import { applyTheme } from "../../utils/theme";
import { chat, snapshot, now } from "../../test/fixtures";
import * as exports from "../../utils/export";
const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>
    {children}
  </QueryClientProvider>
);
beforeEach(() =>
  useAppStore.setState({
    page: "overview",
    search: "Alpha",
    provider: "all",
    range: "all",
    day: null,
    historyDay: "",
    agentsIncluded: true,
    sort: "recent",
    sortDirection: "desc",
  }),
);
describe("dashboard controls", () => {
  it("theme button follows settings changes", () => {
    applyTheme("dark");
    render(<Header />, { wrapper });
    expect(
      screen.getByRole("button", { name: "Switch to light theme" }),
    ).toBeInTheDocument();
    act(() => applyTheme("light"));
    expect(
      screen.getByRole("button", { name: "Switch to dark theme" }),
    ).toBeInTheDocument();
  });
  it("exports searched Overview sessions and ignores the hidden search in Stats", () => {
    const download = vi.spyOn(exports, "download").mockImplementation(() => {}),
      rows = [chat(), chat({ id: "beta", title: "Beta" })],
      data = snapshot({ sessions: rows });
    render(<PageHeading snapshot={data} sessions={rows} />);
    fireEvent.click(screen.getByRole("button", { name: /Export JSON/ }));
    let payload = JSON.parse(download.mock.calls[0][2]);
    expect(payload.sessions).toHaveLength(1);
    expect(payload.sessions[0].title).toBe("Alpha chat");
    expect(payload.filters.search).toBe("Alpha");
    act(() => useAppStore.getState().setPage("stats"));
    fireEvent.click(screen.getByRole("button", { name: /Export JSON/ }));
    payload = JSON.parse(download.mock.calls[1][2]);
    expect(payload.sessions).toHaveLength(2);
    expect(payload.filters.search).toBe("");
  });
  it("retains disabled historical providers in the filter", () => {
    render(
      <FilterBar
        snapshot={snapshot({
          providers: { enabled: ["codex"], setup_done: true },
          sessions: [chat({ provider: "minimax" })],
        })}
      />,
    );
    expect(
      screen.getByRole("button", { name: "M MiniMax" }),
    ).toBeInTheDocument();
  });
});
