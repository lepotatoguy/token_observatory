import { beforeEach, describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WidgetSection } from "./WidgetSection";
import { api } from "../../api/client";
import type { WidgetStatus } from "../../types/widget";
const base: WidgetStatus = {
  enabled: false,
  available: true,
  reason: null,
  running: false,
  starting: false,
  error: null,
};
function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => vi.restoreAllMocks());
describe("WidgetSection", () => {
  it("shows the saved state from the server", async () => {
    vi.spyOn(api, "widget").mockResolvedValue({ ...base, enabled: true, running: true });
    render(<WidgetSection />, { wrapper });
    const toggle = await screen.findByRole("checkbox", { name: "Floating widget" });
    await waitFor(() => expect(toggle).toBeChecked());
    expect(screen.getByText("Running")).toBeInTheDocument();
  });
  it("shows the server's answer after a change, not the request", async () => {
    vi.spyOn(api, "widget").mockResolvedValue(base);
    const save = vi
      .spyOn(api, "setWidget")
      .mockResolvedValue({ ...base, enabled: true, starting: true });
    render(<WidgetSection />, { wrapper });
    const toggle = await screen.findByRole("checkbox", { name: "Floating widget" });
    await waitFor(() => expect(toggle).toBeEnabled());
    fireEvent.click(toggle);
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0]).toBe(true);
    await waitFor(() => expect(toggle).toBeChecked());
    expect(screen.getByText("Starting")).toBeInTheDocument();
  });
  it("reverts the toggle and shows the error when saving fails", async () => {
    vi.spyOn(api, "widget").mockResolvedValue(base);
    vi.spyOn(api, "setWidget").mockRejectedValue(new Error("disk full"));
    render(<WidgetSection />, { wrapper });
    const toggle = await screen.findByRole("checkbox", { name: "Floating widget" });
    await waitFor(() => expect(toggle).toBeEnabled());
    fireEvent.click(toggle);
    expect(await screen.findByText("disk full")).toBeInTheDocument();
    expect(toggle).not.toBeChecked();
  });
  it("disables the toggle and explains when the runtime is missing", async () => {
    vi.spyOn(api, "widget").mockResolvedValue({
      ...base,
      available: false,
      reason: "The widget runtime (PySide6) could not be loaded.",
    });
    render(<WidgetSection />, { wrapper });
    const toggle = await screen.findByRole("checkbox", { name: "Floating widget" });
    expect(await screen.findByText(/PySide6/)).toBeInTheDocument();
    expect(toggle).toBeDisabled();
  });
  it("shows a start failure", async () => {
    vi.spyOn(api, "widget").mockResolvedValue({
      ...base,
      enabled: true,
      error: "The widget keeps exiting at start (code 1). See widget.log.",
    });
    render(<WidgetSection />, { wrapper });
    expect(await screen.findByText(/keeps exiting/)).toBeInTheDocument();
  });
  it("announces status in a polite live region", async () => {
    vi.spyOn(api, "widget").mockResolvedValue(base);
    render(<WidgetSection />, { wrapper });
    await screen.findByRole("checkbox", { name: "Floating widget" });
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
  });
});
