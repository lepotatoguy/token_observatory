import { useEffect, useState } from "react";
import type { Snapshot } from "../../types/snapshot";
import {
  eventTotal,
  compact,
  exact,
  percent,
  providerName,
} from "../../utils/tokens";
import { dayKey, dayStart } from "../../utils/time";
import { saved } from "../../utils/storage";
import { alertOnce } from "../../utils/notifications";
import { useAppStore } from "../../store/useAppStore";
import { providerTokens } from "./LimitsPanel";
import { api } from "../../api/client";
import type { Forecast } from "../../types/forecast";
type Part = {
  provider: string;
  daily: number;
  estimated: boolean;
  source?: "forecast" | "even";
  confidence?: "low" | "medium" | "normal";
  days?: number;
  method?: string;
  shrinkage?: number;
  pairs?: number;
  backtest?: { model_mae: number; baseline_mae: number; days: number } | null;
};
export function suggestedBudget(snapshot: Snapshot, now: number) {
  const parts: { provider: string; daily: number; estimated: boolean }[] = [],
    missing: string[] = [];
  for (const provider of ["claude", "codex", "minimax"].filter((p) =>
    snapshot.providers?.enabled.includes(p),
  )) {
    const quota = snapshot.limits?.[provider],
      week = quota?.secondary,
      used =
        week?.resets_at && quota?.observed_at && (week.used_percent || 0) >= 1
          ? providerTokens(
              snapshot,
              provider,
              week.resets_at - 7 * 86400,
              quota.observed_at,
            )
          : 0;
    if (!used || !week?.resets_at || !week.used_percent) {
      missing.push(provider);
      continue;
    }
    const remaining =
        (used * Math.max(0, 100 - week.used_percent)) / week.used_percent,
      days = Math.max(1, (week.resets_at - now) / 86400);
    parts.push({
      provider,
      daily: Math.round(remaining / days),
      estimated: !!week.resets_estimated,
    });
  }
  return { parts, missing, total: parts.reduce((n, p) => n + p.daily, 0) };
}
/** The forecast's budget per provider, with the browser's even split for any provider it could not budget. */
export function combineBudget(
  browser: ReturnType<typeof suggestedBudget>,
  forecast: Forecast | null,
  enabled: string[],
) {
  const parts: Part[] = [];
  for (const provider of ["claude", "codex", "minimax"].filter((p) =>
    enabled.includes(p),
  )) {
    const f = forecast?.providers?.[provider],
      even = browser.parts.find((p) => p.provider === provider);
    if (f && f.daily !== null && !f.excluded)
      parts.push({
        provider,
        daily: f.daily,
        estimated: f.estimated,
        source: "forecast",
        confidence: f.confidence,
        days: f.days_used,
        method: f.demand_method,
        shrinkage: f.shrinkage,
        pairs: f.calibration_pairs,
        backtest: f.backtest,
      });
    else if (even) parts.push({ ...even, source: "even" });
  }
  return {
    parts,
    missing: enabled.filter((p) => !parts.some((x) => x.provider === p)),
    total: parts.reduce((n, p) => n + p.daily, 0),
  };
}
/** Which algorithm produced a provider's forecast, and how well it predicted that provider's own recent days. */
export function methodNote(part: Part) {
  const test = part.backtest,
    algorithm =
      part.method === "weekday_regression"
        ? `weekday regression (shrinkage ${part.shrinkage})`
        : test
          ? "even split across the remaining days (no weekday pattern beat the flat baseline)"
          : "even split across the remaining days",
    loss = test
      ? `usage-prediction error ${compact(test.model_mae)} tokens a day over ${test.days} test days (flat baseline ${compact(test.baseline_mae)})`
      : "accuracy not measured yet (needs 18 days of history)";
  return `${providerName(part.provider)}: ${algorithm}; tokens per percent from ${part.pairs} readings over ${part.days} days; ${loss}.`;
}
function useForecast(active: boolean) {
  const [forecast, setForecast] = useState<Forecast | null>(null);
  useEffect(() => {
    if (!active) return;
    let alive = true;
    const load = () =>
      api
        .forecast()
        .then((value) => alive && setForecast(value))
        .catch(() => alive && setForecast(null));
    load();
    const timer = setInterval(load, 60000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [active]);
  return active ? forecast : null;
}
export function BudgetPanel({
  snapshot,
  now,
}: {
  snapshot: Snapshot;
  now: number;
}) {
  const [budget, setBudget] = useState<number | null>(() =>
      saved.get("dailyBudget", null),
    ),
    [editing, setEditing] = useState(false),
    [input, setInput] = useState(""),
    history = useAppStore((x) => x.historyDay),
    forecast = useForecast(!history),
    suggested = combineBudget(
      suggestedBudget(snapshot, now),
      forecast,
      snapshot.providers?.enabled || [],
    ),
    providers = [
      ...new Set([
        ...(snapshot.providers?.enabled || ["claude", "codex"]),
        ...snapshot.sessions.map((s) => s.provider),
      ]),
    ],
    usedBy: Record<string, number> = {};
  for (const s of snapshot.sessions)
    for (const e of s.events)
      if (e.at !== null && e.at >= dayStart(dayKey(now)))
        usedBy[s.provider] = (usedBy[s.provider] || 0) + eventTotal(e);
  const used = Object.values(usedBy).reduce((a, b) => a + b, 0),
    scale = budget || suggested.total,
    share = percent(used, scale),
    shares = Object.fromEntries(
      suggested.parts.map((p) => [
        p.provider,
        p.daily * (budget && suggested.total ? budget / suggested.total : 1),
      ]),
    );
  const save = (value: number | null) => {
    saved.set("dailyBudget", value);
    setBudget(value);
    setEditing(false);
  };
  useEffect(() => {
    if (!budget || history) return;
    for (const level of [80, 100])
      if (share >= level)
        alertOnce(
          `budget:${dayKey(now)}:${level}`,
          level >= 100
            ? "Daily token budget reached"
            : `Daily token budget ${level}% used`,
          `${share.toFixed(0)}% of today's budget is used.`,
        );
  }, [share, budget, now, history]);
  return (
    <div className="panel insight" aria-label="Daily budget">
      <div className="insight-title">Today's budget</div>
      {editing ? (
        <form
          className="budget-form"
          onSubmit={(e) => {
            e.preventDefault();
            const value = Number(input);
            if (Number.isInteger(value) && value > 0 && value <= 1e13)
              save(value);
          }}
        >
          <label className="sr-only" htmlFor="budgetInput">
            Daily token budget
          </label>
          <input
            id="budgetInput"
            autoFocus
            type="number"
            min="1"
            max="10000000000000"
            step="1"
            required
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          <button className="button">Save</button>
          {budget && (
            <button type="button" className="quiet" onClick={() => save(null)}>
              Remove
            </button>
          )}
          <button
            type="button"
            className="quiet"
            onClick={() => setEditing(false)}
          >
            Cancel
          </button>
        </form>
      ) : (
        <>
          {scale ? (
            <>
              <div className="limit-head">
                <span title={`${exact(used)} of ${exact(scale)}`}>
                  {compact(used)} of {compact(scale)}{" "}
                  {budget ? "budget" : "suggested"}
                </span>
                <strong
                  className={
                    share >= 100 ? "critical" : share >= 80 ? "high" : ""
                  }
                >
                  {share.toFixed(0)}%
                </strong>
              </div>
              <div
                className="meter"
                role="img"
                aria-label="Today's tokens by provider"
              >
                <div
                  className={`split-meter${suggested.total ? "" : " stacked"}`}
                >
                  {(suggested.total
                    ? suggested.parts.map((p) => p.provider)
                    : providers
                  ).map((p) =>
                    shares[p] ? (
                      <div
                        key={p}
                        className={`split-zone ${p}${percent(usedBy[p] || 0, shares[p]) >= 100 ? " critical" : ""}`}
                        style={{ flexGrow: shares[p] }}
                        data-testid={`budget-zone-${p}`}
                      >
                        <span
                          style={{
                            width: `${Math.min(100, percent(usedBy[p] || 0, shares[p]))}%`,
                          }}
                        />
                      </div>
                    ) : (
                      <span
                        key={p}
                        className={p}
                        style={{
                          width: `${Math.min(100, percent(usedBy[p] || 0, scale))}%`,
                        }}
                      />
                    ),
                  )}
                </div>
                {budget && suggested.total > 0 && (
                  <span
                    className="marker"
                    style={{
                      left: `${Math.min(100, percent(suggested.total, budget))}%`,
                    }}
                    title={`Suggested ${exact(suggested.total)}`}
                  />
                )}
              </div>
              <ul className="budget-split">
                {providers
                  .filter((p) => shares[p] || usedBy[p])
                  .map((p) => (
                    <li key={p}>
                      <i className={`swatch ${p}`} />
                      {providerName(p)}
                      <strong>
                        {compact(usedBy[p] || 0)}
                        {shares[p]
                          ? ` of ${compact(shares[p])} · ${percent(usedBy[p] || 0, shares[p]).toFixed(0)}%`
                          : " today · no share"}
                      </strong>
                    </li>
                  ))}
              </ul>
            </>
          ) : (
            <p className="insight-note">{compact(used)} tokens so far today.</p>
          )}
          <div className="budget-actions">
            <button
              className="button"
              onClick={() => {
                setInput(String(budget || suggested.total || ""));
                setEditing(true);
              }}
            >
              {budget ? "Change budget" : "Set budget"}
            </button>
            {suggested.total > 0 && suggested.total !== budget && (
              <button className="quiet" onClick={() => save(suggested.total)}>
                Use suggested
              </button>
            )}
          </div>
        </>
      )}
      {suggested.total ? (
        <>
          <p className="insight-note">
            Suggested: <strong>{compact(suggested.total)}</strong> a day (
            {suggested.parts
              .map(
                (p) =>
                  `${providerName(p.provider)} ${compact(p.daily)}${p.estimated ? " (estimated reset)" : ""}${p.source === "even" ? " (even split)" : ""}`,
              )
              .join(" + ")}
            ) to stay within weekly limits until reset.{" "}
            {suggested.parts.some((p) => p.source === "forecast")
              ? "Forecast from your usage history."
              : "Estimated from quota snapshots and logged usage."}
            {suggested.missing.length
              ? ` ${suggested.missing.map(providerName).join(", ")} excluded: no usable weekly quota.`
              : ""}
          </p>
          {suggested.parts
            .filter((p) => p.source === "forecast")
            .map((p) => (
              <p key={p.provider} className="insight-note">
                {methodNote(p)}
              </p>
            ))}
        </>
      ) : (
        <p className="insight-note">
          No suggestion yet: it needs a weekly quota with a known reset and some
          usage in the current week.
        </p>
      )}
    </div>
  );
}
