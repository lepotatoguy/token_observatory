import type { Snapshot, Pricing, UpdateStatus } from "../types/snapshot";
import type { ProviderStatus, ProviderChoice } from "../types/providers";
import type { LimitControl, LimitSettings } from "../types/limits";
import type { Forecast } from "../types/forecast";
import type { WidgetStatus } from "../types/widget";
import type { WarmupStatus, WarmupUpdate } from "../types/warmup";
async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    cache: "no-store",
    ...(body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }),
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const error = (await response.json()) as {
        error?: string;
        message?: string;
      };
      message = error.error || error.message || message;
    } catch {
      /* Preserve HTTP status for non-JSON failures. */
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
export const api = {
  usage: () => request<Snapshot>("/api/usage"),
  history: (day: string) =>
    request<Snapshot>(`/api/history/${encodeURIComponent(day)}`),
  refresh: () => request<Snapshot>("/api/refresh", {}),
  pricing: () => request<Pricing>("/api/pricing"),
  providers: () => request<ProviderStatus>("/api/providers"),
  saveProviders: (v: ProviderChoice) =>
    request<ProviderStatus>("/api/providers", v),
  limits: () => request<LimitControl>("/api/limit-control"),
  saveLimits: (v: LimitSettings) =>
    request<LimitControl>("/api/limit-control", v),
  update: () => request<UpdateStatus>("/api/update"),
  saveUpdate: (v: { notify?: boolean; dismiss?: string }) =>
    request<UpdateStatus>("/api/update/settings", v),
  checkUpdate: () => request<UpdateStatus>("/api/update/check", {}),
  installUpdate: () => request<UpdateStatus>("/api/update/install", {}),
  widget: () => request<WidgetStatus>("/api/widget"),
  setWidget: (enabled: boolean) =>
    request<WidgetStatus>("/api/widget", { enabled }),
  warmup: () => request<WarmupStatus>("/api/warmup"),
  setWarmup: (v: WarmupUpdate) => request<WarmupStatus>("/api/warmup", v),
  forecast: (refresh = false) =>
    request<Forecast>(refresh ? "/api/forecast?refresh=1" : "/api/forecast"),
  health: () => request<{ app: string; version: number }>("/api/health"),
};
