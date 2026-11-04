import type { UsageEvent, Tokens } from "../types/session";
export const fields = ["input", "cached", "write", "output"] as const;
export const labels = ["Fresh input", "Cache read", "Cache write", "Output"];
export const colors = ["#8caa77", "#aaa0c5", "#88a6b5", "#d9916b"];
export const exact = (n: number | null | undefined) =>
  Number(n || 0).toLocaleString();
export const compact = (n: number) =>
  n >= 1e9
    ? `${(n / 1e9).toFixed(2)}B`
    : n >= 1e6
      ? `${(n / 1e6).toFixed(2)}M`
      : n >= 1e3
        ? `${(n / 1e3).toFixed(1)}k`
        : exact(n);
export const eventTotal = (e: UsageEvent) =>
  fields.reduce((n, k) => n + (e[k] || 0), 0);
export const sum = (events: UsageEvent[]): Tokens => ({
  input: 0,
  cached: 0,
  write: 0,
  output: 0,
  reasoning: 0,
  total: 0,
  ...Object.fromEntries(
    [...fields, "reasoning", "total"].map((k) => [
      k,
      events.reduce(
        (n, e) => n + (k === "total" ? eventTotal(e) : Number(e[k]) || 0),
        0,
      ),
    ]),
  ),
});
export const percent = (part: number, whole: number) =>
  whole ? (100 * part) / whole : 0;
export const providerNames: Record<string, string> = {
  claude: "Claude Code",
  codex: "Codex",
  minimax: "MiniMax",
  ollama: "Ollama",
  lmstudio: "LM Studio",
  llamacpp: "llama.cpp",
};
export const providerName = (p: string) => providerNames[p] || p;
export const providerIcon = (p: string) =>
  ({
    claude: "✳",
    codex: "◈",
    minimax: "M",
    ollama: "◉",
    lmstudio: "▣",
    llamacpp: "◆",
  })[p] || "•";
