import { beforeEach, describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WarmupSection } from "./WarmupSection";
import { api } from "../../api/client";
import type { WarmupProvider, WarmupStatus } from "../../types/warmup";
const off: WarmupProvider = {
  enabled: false,
  times: [],
  model: null,
  next: null,
  unavailable: null,
  deferred: null,
  last: [],
};
const status = (over: Partial<WarmupStatus["providers"]> = {}): WarmupStatus => ({
  message: "hello",
  providers: {
    claude: off,
    codex: off,
    minimax: { ...off, unavailable: "MiniMax warm-up is unavailable: not verified." },
    ...over,
  },
});
function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => vi.restoreAllMocks());
const ready = async (name: string) => {
  const toggle = await screen.findByRole("checkbox", { name });
  return toggle;
};
describe("WarmupSection", () => {
  it("shows the message, the paid-plan notice and each provider", async () => {
    vi.spyOn(api, "warmup").mockResolvedValue(status());
    render(<WarmupSection />, { wrapper });
    await ready("Claude warm-up");
    expect(screen.getByText(/"hello"/)).toBeInTheDocument();
    expect(screen.getByText(/paid plans/i)).toBeInTheDocument();
    expect(screen.getByText(/small amount of your quota/i)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Codex warm-up" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "MiniMax warm-up" })).toBeInTheDocument();
  });
  it("says so when no time is set and starts the picker on a real time", async () => {
    vi.spyOn(api, "warmup").mockResolvedValue(status());
    render(<WarmupSection />, { wrapper });
    await ready("Claude warm-up");
    expect(screen.getAllByText(/No times yet/).length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Codex new time")).toHaveValue("07:00");
    expect(screen.getAllByText(/New time \(your local time\)/).length).toBe(3);
  });
  it("adds a time and sends the full list", async () => {
    vi.spyOn(api, "warmup").mockResolvedValue(
      status({ claude: { ...off, times: ["18:00"] } }),
    );
    const save = vi.spyOn(api, "setWarmup").mockResolvedValue(
      status({ claude: { ...off, times: ["07:30", "18:00"] } }),
    );
    render(<WarmupSection />, { wrapper });
    await ready("Claude warm-up");
    await screen.findByText("18:00");
    expect(screen.getByLabelText("Claude new time")).toHaveValue("07:00");
    fireEvent.change(screen.getByLabelText("Claude new time"), { target: { value: "07:30" } });
    fireEvent.click(screen.getByRole("button", { name: "Add Claude time" }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0]).toEqual({
      provider: "claude",
      enabled: false,
      times: ["07:30", "18:00"],
      model: null,
    });
    expect(await screen.findByText("07:30")).toBeInTheDocument();
  });
  it("does not add a duplicate or an empty time", async () => {
    vi.spyOn(api, "warmup").mockResolvedValue(status({ claude: { ...off, times: ["07:30"] } }));
    const save = vi.spyOn(api, "setWarmup");
    render(<WarmupSection />, { wrapper });
    await screen.findByText("07:30");
    fireEvent.change(screen.getByLabelText("Claude new time"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Add Claude time" }));
    expect(await screen.findByText(/choose a time/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Claude new time"), { target: { value: "07:30" } });
    fireEvent.click(screen.getByRole("button", { name: "Add Claude time" }));
    expect(await screen.findByText(/already in the list/i)).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });
  it("removes a time", async () => {
    vi.spyOn(api, "warmup").mockResolvedValue(
      status({ codex: { ...off, enabled: true, times: ["06:00", "12:00"] } }),
    );
    const save = vi.spyOn(api, "setWarmup").mockResolvedValue(
      status({ codex: { ...off, enabled: true, times: ["12:00"] } }),
    );
    render(<WarmupSection />, { wrapper });
    await screen.findByText("06:00");
    fireEvent.click(screen.getByRole("button", { name: "Remove Codex time 06:00" }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0]).toMatchObject({ provider: "codex", enabled: true, times: ["12:00"] });
  });
  it("turns a provider on and shows the saved state", async () => {
    vi.spyOn(api, "warmup").mockResolvedValue(status({ claude: { ...off, times: ["07:30"] } }));
    const save = vi.spyOn(api, "setWarmup").mockResolvedValue(
      status({ claude: { ...off, enabled: true, times: ["07:30"], next: "2026-11-07 07:30" } }),
    );
    render(<WarmupSection />, { wrapper });
    const toggle = await ready("Claude warm-up");
    await screen.findByText("07:30");
    fireEvent.click(toggle);
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0]).toMatchObject({ provider: "claude", enabled: true });
    await waitFor(() => expect(toggle).toBeChecked());
    expect(screen.getByText(/Next: 2026-11-07 07:30/)).toBeInTheDocument();
  });
  it("asks for a time before turning a provider on", async () => {
    vi.spyOn(api, "warmup").mockResolvedValue(status());
    const save = vi.spyOn(api, "setWarmup");
    render(<WarmupSection />, { wrapper });
    const toggle = await ready("Claude warm-up");
    fireEvent.click(toggle);
    expect(await screen.findByText(/add a time first/i)).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
    expect(toggle).not.toBeChecked();
  });
  it("shows a server error and keeps the saved state", async () => {
    vi.spyOn(api, "warmup").mockResolvedValue(status({ claude: { ...off, times: ["07:30"] } }));
    vi.spyOn(api, "setWarmup").mockRejectedValue(new Error("times must not repeat"));
    render(<WarmupSection />, { wrapper });
    const toggle = await ready("Claude warm-up");
    await screen.findByText("07:30");
    fireEvent.click(toggle);
    expect(await screen.findByText("times must not repeat")).toBeInTheDocument();
    expect(toggle).not.toBeChecked();
  });
  it("shows the last outcome of each provider", async () => {
    vi.spyOn(api, "warmup").mockResolvedValue(
      status({
        claude: {
          ...off,
          enabled: true,
          times: ["07:30"],
          last: [
            { slot: "2026-11-06 07:30", at: 1, status: "failed", reason: "claude is not signed in" },
            { slot: "2026-11-05 07:30", at: 0, status: "sent", reason: "" },
          ],
        },
      }),
    );
    render(<WarmupSection />, { wrapper });
    await screen.findByText("07:30");
    const card = screen.getByRole("group", { name: "Claude" });
    expect(within(card).getByText(/Last: failed/)).toHaveTextContent("2026-11-06 07:30");
    expect(within(card).getByText(/claude is not signed in/)).toBeInTheDocument();
  });
  it("says when a message is waiting for the limit to reset", async () => {
    vi.spyOn(api, "warmup").mockResolvedValue(
      status({
        claude: {
          ...off,
          enabled: true,
          times: ["07:30"],
          deferred: { slot: "2026-11-06 07:30", send_at: "2026-11-06 11:31" },
        },
      }),
    );
    render(<WarmupSection />, { wrapper });
    expect(await screen.findByText(/waiting for your limit to reset/)).toHaveTextContent(
      "sends at 2026-11-06 11:31",
    );
  });
  it("disables an unavailable provider and says why", async () => {
    vi.spyOn(api, "warmup").mockResolvedValue(status());
    render(<WarmupSection />, { wrapper });
    const toggle = await ready("MiniMax warm-up");
    expect(toggle).toBeDisabled();
    expect(screen.getByText(/not verified/)).toBeInTheDocument();
  });
  it("labels every control and announces results politely", async () => {
    vi.spyOn(api, "warmup").mockResolvedValue(status());
    render(<WarmupSection />, { wrapper });
    await ready("Claude warm-up");
    expect(screen.getByLabelText("Codex new time")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
  });
});
