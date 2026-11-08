import { beforeEach, describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SettingsDialog } from "./SettingsDialog";
import { ProvidersDialog } from "./ProvidersDialog";
import { UpdateDialog } from "./UpdateDialog";
import { LimitControlsDialog } from "./LimitControlsDialog";
import { api } from "../../api/client";
function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => localStorage.clear());
describe("dialogs", () => {
  it("loads the saved theme and persists a new theme", () => {
    localStorage.setItem("to.theme", "dark");
    vi.spyOn(api, "widget").mockResolvedValue({
      enabled: false,
      available: true,
      reason: null,
      running: false,
      starting: false,
      error: null,
    });
    vi.spyOn(api, "update").mockResolvedValue({ current: "1.0", notify: true });
    vi.spyOn(api, "warmup").mockRejectedValue(new Error("offline"));
    render(<SettingsDialog />, { wrapper });
    expect(screen.getByRole("radio", { name: "Dark" })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "Light" }));
    expect(document.documentElement.dataset.theme).toBe("light");
  });
  it("shows install action, release notes and current version when an update exists", async () => {
    vi.spyOn(api, "update").mockResolvedValue({
      current: "1.0",
      notify: true,
      latest: {
        version: "2.0",
        url: "https://example.com/release",
        notes: "Fixed usage collection.",
      },
    });
    render(<UpdateDialog />, { wrapper });
    expect(
      await screen.findByRole("button", { name: "Update now" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/you have 1.0/)).toBeInTheDocument();
    expect(screen.getByText("Fixed usage collection.")).toBeInTheDocument();
  });
  it("saves providers without changing existing MiniMax credentials", async () => {
    vi.spyOn(api, "providers").mockResolvedValue({
      settings: { setup_done: true, enabled: {}, ports: {} },
      names: { minimax: "MiniMax", ollama: "Ollama" },
      enabled: ["minimax"],
      detected: { minimax: "local logs" },
      cloud: ["minimax"],
      local: { ollama: { listen: 11435, target: 11434, server_up: true } },
    });
    const save = vi.spyOn(api, "saveProviders").mockResolvedValue({
      settings: { setup_done: true, enabled: {}, ports: {} },
      names: { minimax: "MiniMax", ollama: "Ollama" },
      enabled: ["minimax", "ollama"],
      detected: {},
      cloud: ["minimax"],
      local: { ollama: { listen: 11435, target: 11434 } },
    });
    render(<ProvidersDialog />, { wrapper });
    await screen.findByText(
      "Reads local MiniMax Code sessions and MiniMax model usage from Claude Code and Codex logs.",
    );
    fireEvent.click(screen.getByRole("checkbox", { name: /Ollama/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        expect.objectContaining({
          enabled: { minimax: true, ollama: true },
          ports: { ollama: { listen: 11435, target: 11434 } },
        }),
        expect.anything(),
      ),
    );
    expect(screen.getByLabelText("MiniMax Coding Plan API key")).toHaveValue("");
  });
  it("saves a MiniMax key and region without returning the saved key", async () => {
    const status = { settings: { setup_done: true, enabled: {}, ports: {} }, names: { minimax: "MiniMax" },
      enabled: ["minimax"], detected: {}, cloud: ["minimax"], local: {}, minimax: { configured: true, region: "global" } };
    vi.spyOn(api, "providers").mockResolvedValue(status);
    const save = vi.spyOn(api, "saveProviders").mockResolvedValue(status);
    render(<ProvidersDialog />, { wrapper });
    const key = await screen.findByLabelText("MiniMax Coding Plan API key");
    expect(key).toHaveValue("");
    fireEvent.change(key, { target: { value: "synthetic-plan-key" } });
    fireEvent.change(screen.getByLabelText("MiniMax API region"), { target: { value: "cn" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({
      minimax: { api_key: "synthetic-plan-key", region: "cn" }
    }), expect.anything()));
  });
  it("removes a saved MiniMax key explicitly", async () => {
    const status = { settings: { setup_done: true, enabled: {}, ports: {} }, names: { minimax: "MiniMax" },
      enabled: ["minimax"], detected: {}, cloud: ["minimax"], local: {}, minimax: { configured: true, region: "global" } };
    vi.spyOn(api, "providers").mockResolvedValue(status);
    const save = vi.spyOn(api, "saveProviders").mockResolvedValue(status);
    render(<ProvidersDialog />, { wrapper });
    fireEvent.click(await screen.findByRole("button", { name: "Remove saved API key", hidden: true }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({
      minimax: { api_key: null, region: "global" }
    }), expect.anything()));
  });
  it("validates warning versus hard limit before saving", async () => {
    vi.spyOn(api, "limits").mockResolvedValue({
      settings: {
        reset_notifications: false,
        claude: { warn: 80, hard: 95, weekly_reserve: 3 },
      },
      events: [],
    });
    const save = vi.spyOn(api, "saveLimits");
    render(<LimitControlsDialog providers={["claude"]} />, { wrapper });
    const field = await screen.findByRole("spinbutton", {
      name: "Claude Code Warning (% used)",
    });
    await waitFor(() => expect(field).toHaveValue(80));
    fireEvent.change(field, { target: { value: "99" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText(
        "Warning threshold must not exceed the hard limit.",
      ),
    ).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });
});
