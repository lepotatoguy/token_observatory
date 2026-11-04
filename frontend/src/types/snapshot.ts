import type { Session, RateLimits } from "./session";
import type { LimitControl, LiveLimits } from "./limits";
export interface Archive {
  dates: string[];
  directory: string;
  saved_at?: number | null;
  error?: string | null;
  interval_seconds?: number;
}
export interface Source {
  provider: string;
  path: string;
  files: number;
}
export interface Snapshot {
  at: number;
  sessions: Session[];
  warnings: string[];
  sources: Source[];
  providers?: { enabled: string[]; setup_done: boolean };
  limits?: Record<string, RateLimits>;
  limit_control?: LimitControl;
  archive?: Archive;
  accounting_version?: number;
  live_limits?: LiveLimits;
  [key: string]: unknown;
}
export interface PriceEntry {
  match: string;
  rates: (number | null)[];
  long_rates?: (number | null)[] | null;
  long_prompt?: number;
  estimated?: boolean;
  local?: boolean;
}
export interface Pricing {
  models?: PriceEntry[];
  prices?: Record<
    string,
    { input: number; cache_read?: number; cache_write?: number; output: number }
  >;
  fetched_at?: number | null;
  error?: string | null;
  source?: string;
  [key: string]: unknown;
}
export interface UpdateStatus {
  current: string;
  notify: boolean;
  checks?: boolean;
  prompt?: boolean;
  latest?: { version: string; notes?: string; url: string } | null;
  progress?: { state: string; message?: string };
  [key: string]: unknown;
}
export type Prices = Pricing;
export type UsageSnapshot = Snapshot;
export type ArchiveManifest = Archive;
