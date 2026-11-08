import { beforeEach, describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { UpdateSection } from "./UpdateSection";
import { api } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { UpdateStatus } from "../../types/snapshot";
const none: UpdateStatus = { current: "1.6.1", notify: true, checks: true, latest: null };
function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  vi.restoreAllMocks();
  useAppStore.setState({ dialog: null });
  vi.spyOn(api, "update").mockResolvedValue(none);
});
const press = async () => {
  const button = await screen.findByRole("button", { name: "Check for updates" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
};
describe("UpdateSection", () => {
  it("says the user is on the latest version", async () => {
    const check = vi.spyOn(api, "checkUpdate").mockResolvedValue(none);
    render(<UpdateSection />, { wrapper });
    await press();
    expect(await screen.findByText(/latest version/)).toHaveTextContent("1.6.1");
    expect(check).toHaveBeenCalledTimes(1);
  });
  it("offers the update dialog when a newer release exists", async () => {
    vi.spyOn(api, "checkUpdate").mockResolvedValue({
      ...none,
      latest: { version: "1.7.0", url: "https://example.com" },
    });
    render(<UpdateSection />, { wrapper });
    await press();
    expect(await screen.findByText(/1\.7\.0 is available/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View update" }));
    expect(useAppStore.getState().dialog).toBe("update");
  });
  it("disables the button while checking", async () => {
    let finish: (value: UpdateStatus) => void = () => {};
    vi.spyOn(api, "checkUpdate").mockReturnValue(new Promise((resolve) => (finish = resolve)));
    render(<UpdateSection />, { wrapper });
    await press();
    expect(await screen.findByRole("button", { name: "Checking" })).toBeDisabled();
    finish(none);
    expect(await screen.findByRole("button", { name: "Check for updates" })).toBeEnabled();
  });
  it("reports a failed request", async () => {
    vi.spyOn(api, "checkUpdate").mockRejectedValue(new Error("HTTP 500"));
    render(<UpdateSection />, { wrapper });
    await press();
    expect(await screen.findByText(/check failed/i)).toBeInTheDocument();
  });
  it("reports a feed failure and keeps the known release", async () => {
    vi.spyOn(api, "checkUpdate").mockResolvedValue({
      ...none,
      error: "Update check failed: offline",
      latest: { version: "1.7.0", url: "https://example.com" },
    });
    render(<UpdateSection />, { wrapper });
    await press();
    expect(await screen.findByText(/check failed/i)).toBeInTheDocument();
    expect(screen.getByText(/1\.7\.0 is available/)).toBeInTheDocument();
  });
  it("explains when update checks are disabled", async () => {
    vi.spyOn(api, "checkUpdate").mockResolvedValue({ ...none, checks: false });
    render(<UpdateSection />, { wrapper });
    await press();
    expect(await screen.findByText(/update checks are disabled/i)).toBeInTheDocument();
  });
  it("announces results in a polite live region", async () => {
    render(<UpdateSection />, { wrapper });
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
  });
});
