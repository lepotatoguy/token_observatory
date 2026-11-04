import type { Snapshot } from "../../types/snapshot";
import { useAppStore } from "../../store/useAppStore";
import { providerName, exact } from "../../utils/tokens";
import { Dialog } from "./Dialog";
export function SourcesDialog({ snapshot }: { snapshot: Snapshot }) {
  const close = useAppStore((s) => s.setDialog);
  return (
    <Dialog title="Data sources & accuracy" onClose={() => close(null)}>
      {snapshot.sources.map((s, i) => (
        <div className="source-item" key={i}>
          <strong>{providerName(s.provider)}</strong> · {exact(s.files)} local
          log files<code>{s.path}</code>
        </div>
      ))}
      <div className="accuracy">
        {snapshot.archive && (
          <p>
            Daily JSON files: {snapshot.archive.directory}. Updated at most once
            per minute when logs change. Calendar dates use this computer's time
            zone. Collection continues while the local service runs.
          </p>
        )}
        <h3>What these numbers mean</h3>
        <p>
          Totals sum recorded fresh input, cached input, cache writes, and
          output. Reasoning is a subset of output and is never added twice.
        </p>
        <p>
          Codex joins log segments by thread and counts each response ID once.
          Legacy logs without response records use cumulative token-count
          deltas. Subagents join their root conversation when included. Claude
          Code deduplicates response usage across content blocks. Cost-state is
          a fallback when response usage is absent.
        </p>
        <p>
          Context shows input plus output from the latest recorded response.
          Codex capacity comes from its log. Claude capacity, compaction
          thresholds, and system/tool/memory/skill token categories are
          unavailable unless explicitly recorded. Configured capacity is
          labeled.
        </p>
        <p>
          Time filters use usage-event timestamps in your browser's local
          timezone. Undated cost-state totals appear only in All retained logs.
          Logs can be incomplete. Older saved captures may contain overlapping
          Codex log segments. Recent means a log changed within five minutes,
          rather than confirmed generation.
        </p>
        <p>
          Estimated API cost uses published per-token prices and excludes
          unpriced models. Reported cost comes from local cost-state when
          present. Neither is a subscription bill.
        </p>
        <p>
          MiniMax usage is read from local MiniMax Code sessions and MiniMax
          model usage in Claude Code and Codex logs. No API key is needed.
          Consumer ChatGPT and Claude browser chats are outside this collector.
          Source logs are read only. Local LLM proxy usage is counted for
          requests through the counting ports configured under Providers. Saved
          LM Studio chats are also imported directly. Only a short title and
          token counts are retained from proxy traffic.
        </p>
        <p>
          <a
            href="https://learn.chatgpt.com/docs/app-server"
            target="_blank"
            rel="noreferrer"
          >
            OpenAI usage telemetry
          </a>{" "}
          ·{" "}
          <a
            href="https://code.claude.com/docs/en/monitoring-usage"
            target="_blank"
            rel="noreferrer"
          >
            Claude Code monitoring
          </a>
        </p>
      </div>
    </Dialog>
  );
}
