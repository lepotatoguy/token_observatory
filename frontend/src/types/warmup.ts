export interface WarmupOutcome {
  slot: string;
  at: number;
  status: "sent" | "failed" | "skipped_active" | "missed";
  reason: string;
}
export interface WarmupProvider {
  enabled: boolean;
  times: string[];
  model: string | null;
  next: string | null;
  unavailable: string | null;
  deferred: { slot: string; send_at: string } | null;
  last: WarmupOutcome[];
}
export type WarmupProviderName = "claude" | "codex" | "minimax";
export interface WarmupStatus {
  message: string;
  providers: Record<WarmupProviderName, WarmupProvider>;
}
export interface WarmupUpdate {
  provider: WarmupProviderName;
  enabled: boolean;
  times: string[];
  model: string | null;
}
