import type { UsageEvent } from "../../types/session";
import { useAppStore } from "../../store/useAppStore";
import { compact, exact } from "../../utils/tokens";
import {
  cutoff,
  date,
  dayKey,
  dayStart,
  shiftDay,
  dayLabel,
} from "../../utils/time";
export function activityBounds(events: UsageEvent[], now: number) {
  return events.reduce(
    (bounds, event) =>
      event.at !== null && Number.isFinite(event.at)
        ? {
            start: Math.min(bounds.start, event.at),
            end: Math.max(bounds.end, event.at),
          }
        : bounds,
    { start: Infinity, end: now },
  );
}
export function ActivityChart({
  events,
  now,
  small = false,
}: {
  events: UsageEvent[];
  now: number;
  small?: boolean;
}) {
  const { range, day, setDay } = useAppStore(),
    dated = events.filter(
      (e): e is UsageEvent & { at: number } =>
        e.at !== null && Number.isFinite(e.at),
    );
  if (!dated.length)
    return (
      <div className="empty-state">No timestamped usage in this range.</div>
    );
  const bounds = activityBounds(dated, now),
    end = day ? dayStart(shiftDay(day, 1)) : bounds.end,
    start = cutoff(range, day, now) || bounds.start,
    span = Math.max(60, end - start),
    days: string[] = [];
  if (span >= 172800)
    for (let key = dayKey(start); dayStart(key) < end; key = shiftDay(key, 1)) {
      days.push(key);
    }
  const count = days.length || (day ? 24 : 36),
    buckets = Array.from({ length: count }, (_, i) => ({
      input: 0,
      output: 0,
      day: days[i],
    }));
  for (const e of dated) {
    const i = days.length
        ? days.indexOf(dayKey(e.at))
        : Math.min(count - 1, Math.floor(((e.at - start) / span) * count)),
      b = buckets[i];
    if (b) {
      b.input += (e.input || 0) + (e.cached || 0) + (e.write || 0);
      b.output += e.output || 0;
    }
  }
  const max = Math.max(1, ...buckets.map((b) => b.input + b.output)),
    width = small ? 440 : 1000,
    height = 165,
    left = 49,
    right = 10,
    top = 12,
    plotHeight = 128,
    step = (width - left - right) / count;
  return (
    <>
      <div className={small ? "conversation-chart" : "chart"}>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={`Token consumption, ${date(start)} to ${date(end)}`}
        >
          {[0, 1, 2, 3].map((i) => (
            <g key={i}>
              <line
                x1={left}
                y1={top + (plotHeight * i) / 3}
                x2={width - right}
                y2={top + (plotHeight * i) / 3}
                style={{ stroke: "var(--track)" }}
                strokeDasharray="3 4"
              />
              <text x={0} y={top + (plotHeight * i) / 3 + 3}>
                {compact(max * (1 - i / 3))}
              </text>
            </g>
          ))}
          {buckets.map((b, i) => {
            const x = left + i * step + 2,
              ih = (b.input / max) * plotHeight,
              oh = (b.output / max) * plotHeight,
              clickable = !!b.day && !small;
            return (
              <g
                key={i}
                role={clickable ? "button" : undefined}
                tabIndex={clickable ? 0 : undefined}
                className={clickable ? "bar-link" : undefined}
                aria-label={clickable ? `Show ${dayLabel(b.day)}` : undefined}
                onClick={() => {
                  if (clickable) setDay(b.day);
                }}
                onKeyDown={(e) => {
                  if (clickable && (e.key === "Enter" || e.key === " ")) {
                    e.preventDefault();
                    setDay(b.day);
                  }
                }}
              >
                <title>
                  {b.day ? dayLabel(b.day) : date(start + (span * i) / count)}
                  {`\nInput: ${exact(b.input)}\nOutput: ${exact(b.output)}`}
                </title>
                <rect
                  x={x}
                  y={top + plotHeight - ih}
                  width={Math.max(1, step - 4)}
                  height={ih}
                  rx={1}
                  fill="#b0c49e"
                />
                <rect
                  x={x}
                  y={top + plotHeight - ih - oh}
                  width={Math.max(1, step - 4)}
                  height={oh}
                  rx={1}
                  fill="#d9916b"
                />
              </g>
            );
          })}
          {[0, 1, 2, 3, 4].map((i) => (
            <text
              key={i}
              x={left + ((width - left - right) * i) / 4}
              y={height - 3}
              textAnchor={i === 0 ? "start" : i === 4 ? "end" : "middle"}
            >
              {new Date((start + (span * i) / 4) * 1000).toLocaleString(
                undefined,
                span < 172800
                  ? { hour: "2-digit", minute: "2-digit" }
                  : { month: "short", day: "numeric" },
              )}
            </text>
          ))}
        </svg>
      </div>
      {!small && (
        <div className="chart-footer">
          <span>
            {day
              ? dayLabel(day)
              : `${new Date(start * 1000).toLocaleDateString()} to ${new Date(end * 1000).toLocaleDateString()}`}
          </span>
          <span>Click a day's bar to view that day</span>
        </div>
      )}
    </>
  );
}
