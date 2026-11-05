import { useEffect } from "react";
import type { Snapshot } from "../../types/snapshot";
import type { QuotaWindow } from "../../types/session";
import type { LimitPreference } from "../../types/limits";
import { useAppStore } from "../../store/useAppStore";
import { eventTotal, providerName } from "../../utils/tokens";
import { countdown, date, relative } from "../../utils/time";
import { alertOnce } from "../../utils/notifications";
export const windowLabel = (minutes: number) =>
  minutes === 300
    ? "5-hour"
    : minutes === 10080
      ? "Weekly"
      : `${minutes}-minute`;
export const hardThreshold = (pref: LimitPreference, minutes: number) =>
  minutes === 10080
    ? pref.weekly_reserve == null
      ? null
      : 100 - pref.weekly_reserve
    : minutes === 300
      ? pref.hard
      : null;
export function providerTokens(
  snapshot: Snapshot,
  provider: string,
  from: number,
  to: number,
) {
  return snapshot.sessions
    .filter((s) => s.provider === provider)
    .reduce(
      (n, s) =>
        n +
        s.events.reduce(
          (m, e) =>
            m +
            (e.at !== null && e.at >= from && e.at <= to ? eventTotal(e) : 0),
          0,
        ),
      0,
    );
}
function forecast(
  snapshot: Snapshot,
  provider: string,
  limit: QuotaWindow,
  now: number,
) {
  const used = limit.used_percent,
    pace =
      limit.window_minutes === 300
        ? 3600
        : limit.window_minutes === 10080
          ? 86400
          : 0;
  if (
    !pace ||
    !limit.resets_at ||
    used == null ||
    used < 1 ||
    used >= 100 ||
    limit.resets_at <= now
  )
    return null;
  const observed = Math.min(
      now,
      snapshot.limits?.[provider]?.observed_at || now,
    ),
    sofar = providerTokens(
      snapshot,
      provider,
      limit.resets_at - limit.window_minutes * 60,
      observed,
    );
  if (!sofar) return null;
  const perPercent = sofar / used,
    current = Math.min(
      100,
      used + providerTokens(snapshot, provider, observed, now) / perPercent,
    ),
    rate = providerTokens(snapshot, provider, now - pace, now) / pace;
  if (!rate)
    return `No logged use in the last ${pace === 3600 ? "hour" : "day"}; stays near ${current.toFixed(0)}% for now.`;
  const hitAt = now + ((100 - current) * perPercent) / rate;
  return hitAt < limit.resets_at
    ? `Estimated to reach 100% around ${date(hitAt)} (in ${countdown(hitAt - now)}), before reset.`
    : `Estimated ${(current + (rate * (limit.resets_at - now)) / perPercent).toFixed(0)}% at reset, at the recent pace.`;
}
export function LimitsPanel({
  snapshot,
  now,
}: {
  snapshot: Snapshot;
  now: number;
}) {
  const { setDialog, historyDay } = useAppStore(),
    limits = snapshot.limits || {};
  useEffect(() => {
    if (historyDay) return;
    const control = snapshot.limit_control;
    if (!control) return;
    for (const e of control.events) {
      if (now - e.at > 1800 || e.at > now) continue;
      if (e.type === "reset" && control.settings.reset_notifications) {
        alertOnce(
          `limit-reset:${e.provider}:${e.limit}:${e.reset}`,
          `${providerName(e.provider || "")} usage window reset`,
          `${windowLabel(e.minutes || 0)} window reset. Any pause for this window has cleared; other limits still apply.`,
        );
      } else if (
        ["threshold", "exhausted"].includes(e.type) &&
        (!e.reset || e.reset > now)
      ) {
        const pref = control.settings[e.provider || ""];
        if (typeof pref !== "object" || !pref) continue;
        const threshold =
          e.mode === "hard" ? hardThreshold(pref, e.minutes || 0) : pref.warn;
        if (threshold === e.threshold)
          alertOnce(
            `limit:${e.provider}:${e.limit}:${e.reset}:${e.mode}:${e.threshold}:${e.type}:${e.at}`,
            `${providerName(e.provider || "")} ${e.mode === "hard" ? "hard limit" : "usage warning"}`,
            `${windowLabel(e.minutes || 0)} usage is ${e.used}%; threshold ${e.threshold}%.`,
          );
      }
    }
  }, [snapshot, now, historyDay]);
  return (
    <div className="panel insight" aria-label="Usage limits">
      <div className="insight-title">
        Usage limits{" "}
        <button className="link" onClick={() => setDialog("limits")}>
          Limit controls
        </button>
      </div>
      {Object.entries(limits).map(([provider, q]) => (
        <div className="limit-group" key={provider}>
          <div className="limit-provider">{providerName(provider)}</div>
          {[q.primary, q.secondary]
            .filter((x) => x != null)
            .map((limit, i) => {
              const used = Math.min(100, Math.max(0, limit.used_percent || 0)),
                pref = snapshot.limit_control?.settings[provider],
                hard =
                  typeof pref === "object" && pref
                    ? hardThreshold(pref, limit.window_minutes)
                    : null,
                warn = typeof pref === "object" && pref ? pref.warn : null;
              return (
                <div className="limit" key={i}>
                  <div className="limit-head">
                    <span>{windowLabel(limit.window_minutes)}</span>
                    <strong>
                      {limit.used_percent == null
                        ? "Unreported"
                        : `${+limit.used_percent.toFixed(1)}% used · ${+Math.max(0, 100 - limit.used_percent).toFixed(1)}% left`}
                    </strong>
                  </div>
                  <div
                    className={`gauge${used >= 90 ? " critical" : used >= 70 ? " high" : ""}`}
                    role="progressbar"
                    aria-label={`${providerName(provider)} ${windowLabel(limit.window_minutes)} quota`}
                    aria-valuenow={used}
                    aria-valuemin={0}
                    aria-valuemax={100}
                  >
                    <span style={{ width: `${used}%` }} />
                  </div>
                  <small title={date(limit.resets_at)}>
                    {!limit.resets_at
                      ? "reset time unknown"
                      : limit.resets_at <= now
                        ? "reset since this snapshot"
                        : `resets in ${limit.resets_estimated ? "~" : ""}${countdown(limit.resets_at - now)}${limit.resets_estimated ? " (estimated)" : ""}`}
                  </small>
                  <small
                    className="forecast"
                    title="Estimated from logged tokens. Other clients also count toward account usage."
                  >
                    {forecast(snapshot, provider, limit, now)}
                  </small>
                  {!historyDay &&
                    (!limit.resets_at || limit.resets_at > now) &&
                    ((hard !== null && used >= hard) ||
                      (warn != null && used >= warn)) && (
                      <p className="limit-error" role="alert">
                        {providerName(provider)}{" "}
                        {windowLabel(limit.window_minutes)}:{" "}
                        {hard !== null && used >= hard
                          ? "hard limit"
                          : "warning"}{" "}
                        reached.
                      </p>
                    )}
                </div>
              );
            })}
          <p className="insight-note">
            {q.source === "live"
              ? provider === "minimax" ? "Checked with MiniMax" : "Checked with the coding client"
              : "Locally recorded quota"}{" "}
            · {relative(q.observed_at, now)}
            {q.error ? ` · ${q.error}` : ""}
          </p>
        </div>
      ))}
      {!historyDay && Object.entries(snapshot.live_limits?.errors || {}).map(([provider, error]) => (
        <p className="limit-error" role="status" key={provider}>
          {providerName(provider)}: {error}{limits[provider] ? " Showing the last recorded quota." : ""}
        </p>
      ))}
      {!Object.keys(limits).length && (
        <p className="insight-note">
          No account quota recorded. Refresh to check supported clients.
        </p>
      )}
      {(snapshot.providers?.enabled || []).includes("minimax") &&
        !limits.minimax && (
          <p className="insight-note">
            MiniMax quota is unavailable. Sign in to MiniMax Code or add a Coding Plan API key in Providers.
          </p>
        )}
    </div>
  );
}
