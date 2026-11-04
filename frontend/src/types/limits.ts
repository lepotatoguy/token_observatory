export interface LimitPreference {
  warn: number | null;
  hard: number | null;
  weekly_reserve: number | null;
}
export interface LimitSettings {
  reset_notifications: boolean;
  claude?: LimitPreference;
  codex?: LimitPreference;
  minimax?: LimitPreference;
  [key: string]: LimitPreference | boolean | undefined;
}
export interface LimitEvent {
  at: number;
  type: string;
  provider?: string;
  limit?: string;
  minutes?: number;
  used?: number;
  mode?: string;
  threshold?: number;
  reset?: number;
  [key: string]: unknown;
}
export interface LimitControl {
  settings: LimitSettings;
  events: LimitEvent[];
  hooks?: Record<string, unknown>;
  [key: string]: unknown;
}
export type { QuotaWindow as LimitWindow, RateLimits } from "./session";
import type { RateLimits } from "./session";
export interface LiveLimits {
  checked_at: number | null;
  errors: Record<string, string>;
  claude?: RateLimits | null;
  codex?: RateLimits | null;
  minimax?: RateLimits | null;
}
