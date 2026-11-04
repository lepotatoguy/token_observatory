export type Provider = string;
export interface Tokens {
  input: number;
  cached: number;
  write: number;
  output: number;
  reasoning: number;
  total: number;
}
export interface UsageEvent extends Partial<Tokens> {
  at: number | null;
  model?: string;
  cache_unreported?: boolean;
  response_id?: string;
  [key: string]: unknown;
}
export interface QuotaWindow {
  used_percent: number | null;
  window_minutes: number;
  resets_at: number | null;
  resets_estimated?: boolean;
}
export interface RateLimits {
  primary?: QuotaWindow | null;
  secondary?: QuotaWindow | null;
  observed_at?: number;
  source?: string;
  error?: string;
  [key: string]: unknown;
}
export interface Session {
  id: string;
  provider: Provider;
  session_id: string;
  conversation_id?: string;
  subagent?: boolean;
  title: string;
  project: string | null;
  model: string;
  models: string[];
  events: UsageEvent[];
  totals: Tokens;
  scope?: Tokens;
  last: number | null;
  modified: number;
  source: string;
  source_files?: string[];
  thread_ids?: string[];
  agent_count?: number;
  compactions: number;
  usage_source: string;
  capacity: number | null;
  context: number | null;
  capacity_source?: string;
  latest_usage?: Tokens | null;
  latest_usage_at?: number | null;
  cache_unreported?: boolean;
  rate_limits?: RateLimits | null;
  reported_cost: number | null;
  cost_source?: string;
  parse_errors: number;
  accounting_version?: number;
  [key: string]: unknown;
}
export interface ScopedSession extends Session {
  scope: Tokens;
}
export type TokenEvent = UsageEvent;
export type SessionTotals = Tokens;
