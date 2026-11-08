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
  calibration?: "single" | "by_type" | null;
  rolling?: { mae_points: number; single_mae_points: number; readings: number } | null;
  check?: { within: number; scored: number } | null;
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
        calibration: f.calibration_kind,
        rolling: f.rolling,
        check: f.budget_check,
      });
    else if (even) parts.push(forecast ? { ...even, source: "even" } : even);
  }
  return {
    parts,
    missing: enabled.filter((p) => !parts.some((x) => x.provider === p)),
    total: parts.reduce((n, p) => n + p.daily, 0),
  };
}
/** Plain-language account of the forecast: which model ran, how it scored on the user's own days, and who fell back. */
export function forecastExplanation(parts: Part[]) {
  const used = parts.filter((p) => p.source === "forecast"),
    simple = parts.filter((p) => p.source === "even"),
    names = (list: Part[]) => list.map((p) => providerName(p.provider)).join(", "),
    scored = used.filter((p) => p.backtest),
    weekday = used.filter((p) => p.method === "weekday_regression"),
    flat = used.filter((p) => p.method !== "weekday_regression" && p.backtest),
    unscored = used.filter((p) => !p.backtest),
    text: string[] = [];
  if (used.length) {
    text.push(
      "How it is forecast: a small regression model (ridge-style) learns how much you use on each weekday from your last 30 days, and the weekly limit you have left is spread over the days until reset accordingly.",
    );
    if (scored.length)
      text.push(
        `Loss (mean absolute error on days it had not seen): ${scored
          .map(
            (p) =>
              `${providerName(p.provider)} ${compact(p.backtest!.model_mae)} tokens a day against ${compact(p.backtest!.baseline_mae)} for a flat guess over ${p.backtest!.days} days`,
          )
          .join("; ")}.`,
      );
    if (weekday.length)
      text.push(
        `${names(weekday)}: the weekday pattern beat the flat guess, so heavier days get a bigger share.`,
      );
    if (flat.length)
      text.push(
        `${names(flat)}: no weekday pattern beat the flat guess, so days are weighted evenly.`,
      );
    if (unscored.length)
      text.push(
        `${names(unscored)}: too few days to score yet (needs 18), so days are weighted evenly.`,
      );
  }
  if (simple.length)
    text.push(
      `${names(simple)}: too little history for the forecast, so a simple estimate from this week's usage is used.`,
    );
  return text.join(" ");
}
/** How each forecast provider's tokens-per-percent was learned, how well it predicted past readings, and past days within budget. */
export function calibrationNote(parts: Part[]) {
  const lines = parts
    .filter((p) => p.source === "forecast" && p.calibration)
    .map((p) => {
      const how =
          p.calibration === "by_type"
            ? "learns how much each kind of token (new input, cached input, output) costs your limit"
            : "uses one tokens-per-percent ratio (too few readings, or the detailed method was not more accurate)",
        error = p.rolling
          ? `; it predicted past weekly-limit changes within ${p.rolling.mae_points.toFixed(1)} points (one ratio: ${p.rolling.single_mae_points.toFixed(1)}) over ${p.rolling.readings} ${p.rolling.readings === 1 ? "reading" : "readings"}`
          : "",
        days = p.check
          ? `; you stayed within the day's budget on ${p.check.within} of ${p.check.scored} past days`
          : "";
      return `${providerName(p.provider)}: ${how}${error}${days}.`;
    });
  return lines.length ? `Calibration: ${lines.join(" ")}` : "";
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
            Suggested daily budget from your weekly limits:{" "}
            <strong>{compact(suggested.total)}</strong> a day (
            {suggested.parts
              .map(
                (p) =>
                  `${providerName(p.provider)} ${compact(p.daily)}${p.estimated ? " (estimated reset)" : ""}${p.source === "even" ? " (simple estimate)" : ""}`,
              )
              .join(" + ")}
            ). Spending this much each day makes your remaining weekly limit
            last until it resets.
            {suggested.missing.length
              ? ` ${suggested.missing.map(providerName).join(", ")} excluded: no usable weekly quota.`
              : ""}
          </p>
          <p className="insight-note">
            {forecastExplanation(suggested.parts) ||
              "Estimated from quota snapshots and logged usage."}
          </p>
          {calibrationNote(suggested.parts) && (
            <p className="insight-note">{calibrationNote(suggested.parts)}</p>
          )}
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
