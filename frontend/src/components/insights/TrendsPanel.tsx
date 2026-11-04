import type { Snapshot } from "../../types/snapshot";
import { useAppStore } from "../../store/useAppStore";
import { eventTotal, compact, exact } from "../../utils/tokens";
import { dayStart, dayKey, shiftDay, dayLabel } from "../../utils/time";
const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const change = (a: number, b: number) =>
  b
    ? `${a >= b ? "+" : ""}${((100 * (a - b)) / b).toFixed(0)}%`
    : a
      ? "New usage"
      : "No change";
export function TrendsPanel({
  snapshot,
  now,
}: {
  snapshot: Snapshot;
  now: number;
}) {
  const { provider, agentsIncluded, setDay } = useAppStore(),
    sessions = snapshot.sessions.filter(
      (s) =>
        (provider === "all" || s.provider === provider) &&
        (agentsIncluded || !s.subagent),
    ),
    days = new Map<string, number>(),
    grid = Array.from({ length: 7 }, () => Array<number>(24).fill(0)),
    todayKey = dayKey(now),
    heatStart = dayStart(shiftDay(todayKey, -27));
  for (const s of sessions)
    for (const e of s.events) {
      if (e.at === null || e.at > now) continue;
      const key = dayKey(e.at);
      days.set(key, (days.get(key) || 0) + eventTotal(e));
      if (e.at >= heatStart) {
        const d = new Date(e.at * 1000);
        grid[(d.getDay() + 6) % 7][d.getHours()] += eventTotal(e);
      }
    }
  const at = (n: number) => days.get(shiftDay(todayKey, n)) || 0,
    today = at(0),
    week = Array.from({ length: 7 }, (_, i) => at(-i)).reduce(
      (a, b) => a + b,
      0,
    ),
    prior = Array.from({ length: 7 }, (_, i) => at(-i - 7)).reduce(
      (a, b) => a + b,
      0,
    ),
    average =
      Array.from({ length: 7 }, (_, i) => at(-i - 1)).reduce(
        (a, b) => a + b,
        0,
      ) / 7,
    busiest = [...days]
      .filter(([key]) => key >= shiftDay(todayKey, -29))
      .sort((a, b) => b[1] - a[1])[0],
    max = Math.max(1, ...grid.flat());
  return (
    <section className="panel" aria-label="Usage trends">
      <div className="panel-heading">
        <div>
          <h2>Trends</h2>
          <p>From all retained logs for the selected provider.</p>
        </div>
      </div>
      <div className="trend-stats">
        <div>
          <span>Today</span>
          <strong>{compact(today)}</strong>
          <small>
            {change(today, average)} vs 7-day average ({compact(average)})
          </small>
        </div>
        <div>
          <span>Last 7 days</span>
          <strong>{compact(week)}</strong>
          <small>{change(week, prior)} vs the 7 days before</small>
        </div>
      </div>
      <p className="insight-note">
        Busiest day in the last 30 days:{" "}
        {busiest ? (
          <>
            <button className="link" onClick={() => setDay(busiest[0])}>
              {dayLabel(busiest[0])}
            </button>
            , {compact(busiest[1])}
          </>
        ) : (
          "none yet"
        )}
      </p>
      <div className="breakdown-heading">
        When you use tokens <span>last 28 days</span>
      </div>
      <div className="heatmap">
        {grid.map((row, d) => (
          <div key={d} style={{ display: "contents" }}>
            <span className="heat-label">{weekdays[d]}</span>
            {row.map((v, h) => (
              <span
                key={h}
                className="heat-cell"
                style={{ opacity: v ? 0.15 + (0.85 * v) / max : 0.06 }}
                title={`${weekdays[d]} ${String(h).padStart(2, "0")}:00 · ${exact(v)} tokens`}
              />
            ))}
          </div>
        ))}
        <span />
        {[0, 6, 12, 18].map((h) => (
          <span key={h} className="heat-hour" style={{ gridColumn: h + 2 }}>
            {String(h).padStart(2, "0")}
          </span>
        ))}
      </div>
    </section>
  );
}
