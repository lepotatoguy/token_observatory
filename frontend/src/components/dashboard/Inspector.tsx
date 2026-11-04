import type { ScopedSession, UsageEvent, Tokens } from "../../types/session";
import { useAppStore } from "../../store/useAppStore";
import {
  sum,
  fields,
  labels,
  colors,
  compact,
  exact,
  eventTotal,
  providerName,
} from "../../utils/tokens";
import { date, relative } from "../../utils/time";
import { contextPercent } from "../../utils/conversations";
import { ActivityChart } from "./ActivityChart";
function Breakdown({
  usage,
  events,
  unavailable,
}: {
  usage: Tokens;
  events: UsageEvent[];
  unavailable: boolean;
}) {
  const missing = events.some((e) => e.cache_unreported),
    allMissing = events.length > 0 && events.every((e) => e.cache_unreported),
    input = usage.input + usage.cached + usage.write;
  return (
    <>
      <div className="breakdown-heading">
        Token breakdown{" "}
        <span>{unavailable ? "Unreported" : exact(usage.total)} recorded</span>
      </div>
      <div className="usage-bar">
        {fields.map((key, i) => (
          <span
            key={key}
            style={{
              width: `${usage.total ? (100 * usage[key]) / usage.total : 0}%`,
              background: colors[i],
            }}
          />
        ))}
      </div>
      {fields.map((key, i) => (
        <div className="breakdown-row" key={key}>
          <span>
            <i className="swatch" style={{ background: colors[i] }} />
            {missing
              ? key === "input"
                ? "Input (cache split incomplete)"
                : `${labels[i]} (recorded)`
              : labels[i]}
          </span>
          <strong>
            {unavailable ||
            (allMissing && (key === "cached" || key === "write"))
              ? "Unreported"
              : exact(usage[key])}
          </strong>
        </div>
      ))}
      <div className="breakdown-row">
        <span>↳ Reasoning, included in output</span>
        <strong>{unavailable ? "Unreported" : exact(usage.reasoning)}</strong>
      </div>
      <p className="insight-note">
        {missing
          ? "Cache breakdown is incomplete."
          : `${(input ? (100 * usage.cached) / input : 0).toFixed(1)}% of input served from cache.`}
      </p>
    </>
  );
}
export function Inspector({
  session: s,
  sessions,
  now,
}: {
  session?: ScopedSession;
  sessions: ScopedSession[];
  now: number;
}) {
  const setSelected = useAppStore((x) => x.setSelected),
    events = s ? s.events : sessions.flatMap((x) => x.events),
    usage = s ? s.scope : sum(events),
    pct = s ? contextPercent(s) : null,
    missing = sessions.filter((x) => x.usage_source === "unavailable").length;
  return (
    <section className="panel inspector" aria-label="Selected conversation">
      <div className="inspector-label">
        {s ? "CONVERSATION INSPECTOR" : "COMBINED USAGE"}
      </div>
      {s && (
        <button className="quiet" onClick={() => setSelected(null)}>
          ← All conversations
        </button>
      )}
      <h2>{s ? s.title : "All conversations"}</h2>
      <div className="meta">
        {s ? (
          <>
            <span className={`provider-badge ${s.provider}`}>
              {providerName(s.provider)}
            </span>{" "}
            {s.model}
          </>
        ) : (
          `${sessions.length} chats matching current filters and search`
        )}
      </div>
      <div className="context-card">
        {s ? (
          <>
            <div className="context-heading">
              <span>◒ Context window</span>
              <strong>
                {pct === null ? "Capacity unreported" : `${pct.toFixed(1)}%`}
              </strong>
            </div>
            <p>
              {s.context == null
                ? "Latest request usage unavailable"
                : `${exact(s.context)} tokens, latest recorded input + output`}
            </p>
            <div className="context-track">
              <span
                className="context-used"
                style={{ width: `${Math.min(100, pct || 0)}%` }}
              />
            </div>
            <div className="context-footer">
              <span>
                {s.capacity
                  ? `${compact(s.capacity)} ${s.capacity_source === "configured" ? "configured capacity" : s.capacity_source === "logged" ? "logged capacity" : s.capacity_source || "capacity source unreported"}`
                  : "Window size unreported"}
              </span>
              <span>
                {s.capacity && s.context != null
                  ? `${compact(Math.max(0, s.capacity - s.context))} free`
                  : "Free space unknown"}
              </span>
            </div>
            {s.latest_usage ? (
              <>
                <div className="context-categories">
                  {([...fields, "reasoning"] as const).map((key, i) => (
                    <span key={key}>
                      {key === "reasoning"
                        ? "Reasoning (in output)"
                        : labels[i]}
                      <b>
                        {s.cache_unreported &&
                        (key === "cached" || key === "write")
                          ? "Unreported"
                          : exact(s.latest_usage?.[key])}
                      </b>
                    </span>
                  ))}
                  <span>
                    Free space
                    <b>
                      {s.capacity && s.context != null
                        ? exact(Math.max(0, s.capacity - s.context))
                        : "Unreported"}
                    </b>
                  </span>
                </div>
                <p className="context-note">
                  Latest request: {date(s.latest_usage_at)}.{" "}
                  {providerName(s.provider)} logs omit system, tool, memory, and
                  skill token attribution.
                  {s.capacity_source === "configured"
                    ? " Capacity is configured beside the history folder."
                    : ""}
                </p>
              </>
            ) : (
              <p className="context-note">
                No per-response detail in this capture.
              </p>
            )}
          </>
        ) : (
          <>
            <div className="context-heading">
              Context windows are per conversation
            </div>
            <p>Select a chat to inspect its context usage and capacity.</p>
          </>
        )}
      </div>
      <div className="chat-activity">
        <div className="breakdown-heading">
          {s ? "Chat" : "Combined"} token activity
        </div>
        <p>
          Selected time range · input and cache in green · output in orange
          {s?.agent_count ? ` · includes ${s.agent_count} subagents` : ""}
        </p>
        <ActivityChart events={events} now={now} small />
      </div>
      <Breakdown
        usage={usage}
        events={events}
        unavailable={
          s
            ? s.usage_source === "unavailable"
            : sessions.length > 0 && missing === sessions.length
        }
      />
      <div className="detail-facts">
        {(s
          ? [
              ["Recorded compactions, lifetime", exact(s.compactions)],
              ["Usage source", s.usage_source],
              ["Usage updates in range", exact(events.length)],
              [
                "Lifetime recorded tokens",
                s.usage_source === "unavailable"
                  ? "Unreported"
                  : exact(s.totals.total),
              ],
              [
                "Reported lifetime cost",
                s.reported_cost == null
                  ? "Unreported"
                  : `$${s.reported_cost.toFixed(2)}`,
              ],
              ["Session ID", s.session_id],
            ]
          : [
              ["Usage updates in range", exact(events.length)],
              ["Chats with unreported usage", exact(missing)],
            ]
        ).map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
        {s &&
          [s.rate_limits?.primary, s.rate_limits?.secondary]
            .filter((x) => x != null)
            .map((limit, i) => (
              <div key={i}>
                <span>
                  {limit.window_minutes === 300
                    ? "5-hour"
                    : limit.window_minutes === 10080
                      ? "Weekly"
                      : `${limit.window_minutes}-minute`}{" "}
                  account quota
                </span>
                <strong>
                  {limit.used_percent ?? "Unreported"}% used · resets{" "}
                  {date(limit.resets_at)}
                </strong>
              </div>
            ))}
      </div>
      {s && (
        <details>
          <summary>Recent usage updates</summary>
          <div className="event-list">
            {[...s.events]
              .sort((a, b) => (b.at || 0) - (a.at || 0))
              .slice(0, 20)
              .map((e, i) => (
                <div key={i}>
                  <span title={date(e.at)}>{relative(e.at, now)}</span>
                  <span>{exact(eventTotal(e))} tokens</span>
                </div>
              ))}
            {!s.events.length && "No recorded usage."}
          </div>
          <div className="source-path">{s.source}</div>
        </details>
      )}
    </section>
  );
}
