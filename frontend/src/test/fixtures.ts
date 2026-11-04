import type { ScopedSession } from "../types/session";
import type { Snapshot } from "../types/snapshot";
import { sum } from "../utils/tokens";
export const now = 1730000000;
export function chat(overrides: Partial<ScopedSession> = {}): ScopedSession {
  const events = [
      {
        at: now - 60,
        input: 1000,
        cached: 500,
        write: 100,
        output: 400,
        reasoning: 80,
        model: "test-model",
      },
    ],
    totals = sum(events);
  return {
    id: "claude-1",
    provider: "claude",
    session_id: "root",
    title: "Alpha chat",
    project: "test-project",
    model: "test-model",
    models: ["test-model"],
    events,
    totals,
    scope: totals,
    last: now - 60,
    modified: now,
    source: "/tmp/test.jsonl",
    compactions: 0,
    usage_source: "response usage",
    capacity: 10000,
    context: 2000,
    reported_cost: null,
    parse_errors: 0,
    ...overrides,
  };
}
export function snapshot(overrides: Partial<Snapshot> = {}): Snapshot {
  return {
    at: now,
    sessions: [chat()],
    warnings: [],
    sources: [{ provider: "claude", path: "/tmp/claude", files: 1 }],
    providers: { enabled: ["claude", "codex"], setup_done: true },
    ...overrides,
  };
}
