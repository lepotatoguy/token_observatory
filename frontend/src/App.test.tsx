import { it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { api } from "./api/client";
import { useAppStore } from "./store/useAppStore";
import { snapshot } from "./test/fixtures";
it("returns from unreadable archive days to live usage", async () => {
  vi.spyOn(api, "history").mockRejectedValue(new Error("HTTP 404"));
  vi.spyOn(api, "usage").mockResolvedValue(snapshot());
  vi.spyOn(api, "pricing").mockResolvedValue({ models: [] });
  vi.spyOn(api, "update").mockResolvedValue({
    current: "2.0",
    notify: false,
    checks: false,
  });
  useAppStore.setState({
    historyDay: "2024-01-01",
    range: "all",
    page: "overview",
    dialog: null,
    paused: false,
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  expect(
    await screen.findByText("Could not read local telemetry: HTTP 404"),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Return to Live" }));
  expect(await screen.findByText("Usage overview")).toBeInTheDocument();
  expect(useAppStore.getState().historyDay).toBe("");
  expect(api.usage).toHaveBeenCalled();
});
