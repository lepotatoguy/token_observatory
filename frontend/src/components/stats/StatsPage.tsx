import type { CSSProperties, ReactNode } from "react";
import type { ScopedSession } from "../../types/session";
import type { Prices, Snapshot } from "../../types/snapshot";
import { statsData, statsSummary } from "../../utils/stats";
import { compact, eventTotal, exact, sum } from "../../utils/tokens";
import { cutoff, date, dayStart, shiftDay } from "../../utils/time";
import { eventPricing, money } from "../../utils/cost";

type Point = [string, number | null];
const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const fmt = (value: number | null | undefined) =>
  value == null ? "Unreported" : exact(Math.round(value));
const ratio = (n: number, d: number) =>
  d ? `${((100 * n) / d).toFixed(1)}%` : "Unreported";

function Panel({
  title,
  note,
  children,
  wide = false,
}: {
  title: string;
  note: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <section className={`panel stats-panel${wide ? " stats-wide" : ""}`}>
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          <p>{note}</p>
        </div>
      </div>
      {children}
    </section>
  );
}
function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="stats-facts">
      {rows.map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
function Bars({ rows, total }: { rows: [string, number][]; total?: number }) {
  const maximum = Math.max(1, ...rows.map((r) => r[1]));
  if (!rows.some((r) => r[1]))
    return <p className="empty-state">No recorded usage in this range.</p>;
  return (
    <div className="stats-bars">
      {rows.map(([name, value], index) => (
        <div className="stats-bar-row" key={`${name}-${index}`}>
          <div>
            <span title={name}>{name}</span>
            <strong>
              {exact(value)}{" "}
              {total != null && <small>{ratio(value, total)}</small>}
            </strong>
          </div>
          <div className="stats-track">
            <span style={{ width: `${(100 * value) / maximum}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}
function Ranking({ map }: { map: Map<string, number> }) {
  const rows = [...map].sort((a, b) => b[1] - a[1]),
    shown = rows.slice(0, 7);
  if (rows.length > 7)
    shown.push(["Other", rows.slice(7).reduce((n, r) => n + r[1], 0)]);
  return <Bars rows={shown} total={rows.reduce((n, r) => n + r[1], 0)} />;
}
function Line({
  points,
  label,
  percentage = false,
  xLabel = "Date",
}: {
  points: Point[];
  label: string;
  percentage?: boolean;
  xLabel?: string;
}) {
  if (!points.length)
    return <p className="empty-state">No dated usage in this range.</p>;
  const maximum = percentage
    ? 100
    : Math.max(1, ...points.map((p) => p[1] || 0));
  const x = (i: number) =>
    58 + 562 * (points.length === 1 ? 0.5 : i / (points.length - 1));
  const y = (value: number) => 142 - (122 * value) / maximum;
  let path = "",
    connected = false;
  for (const [i, p] of points.entries()) {
    if (p[1] == null) {
      connected = false;
      continue;
    }
    path += `${connected ? "L" : "M"}${x(i)},${y(p[1])} `;
    connected = true;
  }
  return (
    <>
      <div className="stats-line">
        <svg viewBox="0 0 640 180" role="img" aria-label={label}>
          <title>{label}</title>
          {[0, 0.5, 1].map((t) => (
            <g key={t}>
              <line
                x1="58"
                x2="620"
                y1={y(maximum * t)}
                y2={y(maximum * t)}
                className="stats-gridline"
              />
              <text x="50" y={y(maximum * t) + 4} textAnchor="end">
                {percentage ? `${maximum * t}%` : compact(maximum * t)}
              </text>
            </g>
          ))}
          <path d={path} />
          {[
            ...new Set([
              0,
              Math.floor((points.length - 1) / 2),
              points.length - 1,
            ]),
          ].map((i) => (
            <text key={i} x={x(i)} y="168" textAnchor="middle">
              {xLabel === "Date" ? points[i][0].slice(5) : points[i][0]}
            </text>
          ))}
          {points.map(([label, value], i) =>
            value == null ? null : (
              <circle key={i} cx={x(i)} cy={y(value)} r="3">
                <title>
                  {label}: {percentage ? `${value.toFixed(1)}%` : exact(value)}
                </title>
              </circle>
            ),
          )}
        </svg>
      </div>
      <details className="stats-data">
        <summary>View data</summary>
        <div className="stats-data-scroll">
          <table>
            <thead>
              <tr>
                <th>{xLabel}</th>
                <th>{label}</th>
              </tr>
            </thead>
            <tbody>
              {points.map(([key, value]) => (
                <tr key={key}>
                  <td>{key}</td>
                  <td>
                    {value == null
                      ? "Unreported"
                      : percentage
                        ? `${value.toFixed(1)}%`
                        : exact(value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}
function Summary({ values }: { values: number[] }) {
  const s = statsSummary(values);
  return (
    <Facts
      rows={
        s
          ? [
              ["Minimum", fmt(s.min)],
              ["25th percentile", fmt(s.q1)],
              ["Median", fmt(s.median)],
              ["75th percentile", fmt(s.q3)],
              ["Maximum", fmt(s.max)],
              ["Mean", fmt(s.mean)],
              ["Standard deviation", fmt(s.deviation)],
              [
                "Coefficient of variation",
                s.cv == null ? "Unreported" : `${s.cv.toFixed(2)} × mean`,
              ],
            ]
          : [["Sample", "No recorded usage"]]
      }
    />
  );
}
interface Props {
  sessions: ScopedSession[];
  snapshot: Snapshot;
  now: number;
  range?: string;
  day?: string | null;
  provider?: string;
  agentsIncluded?: boolean;
  prices?: Prices;
}

export default function StatsPage({
  sessions,
  snapshot,
  now,
  range = "all",
  day = null,
  provider = "all",
  agentsIncluded = true,
  prices,
}: Props) {
  const d = statsData(sessions),
    total = d.totals.total;
  let cumulative = 0;
  const running: Point[] = d.timeline.map(([key, value]) => [
    key,
    (cumulative += value.total),
  ]);
  const input = d.totals.input + d.totals.cached + d.totals.write;
  const weekdayCounts = Array<number>(7).fill(0);
  for (const [key] of d.timeline)
    weekdayCounts[(new Date(dayStart(key) * 1000).getDay() + 6) % 7]++;
  const hourly: [string, number][] = Array.from({ length: 24 }, (_, hour) => [
    `${String(hour).padStart(2, "0")}:00`,
    d.hours.reduce((n, row) => n + row[hour], 0),
  ]);
  const peaks = [...d.days].sort((a, b) => b[1].total - a[1].total),
    hourPeak = [...hourly].sort((a, b) => b[1] - a[1])[0];
  const topCount = d.chats.length
    ? Math.max(1, Math.ceil(d.chats.length * 0.1))
    : 0;
  const concentration: Point[] = [
    ["0%", 0],
    ...Array.from({ length: 10 }, (_, i): Point => [
      `${(i + 1) * 10}%`,
      total
        ? (100 *
            d.chats
              .slice(0, Math.ceil((d.chats.length * (i + 1)) / 10))
              .reduce((n, s) => n + s.scope.total, 0)) /
          total
        : 0,
    ]),
  ];
  const start = cutoff(range, day, now),
    end = Math.min(day ? dayStart(shiftDay(day, 1)) : now, now);
  const previousEvents =
    start && end > start
      ? snapshot.sessions
          .filter(
            (s) =>
              (provider === "all" || s.provider === provider) &&
              (agentsIncluded || !s.subagent),
          )
          .flatMap((s) => s.events)
          .filter(
            (e) =>
              typeof e.at === "number" &&
              e.at >= start - (end - start) &&
              e.at < start,
          )
      : [];
  const current = sum(
      d.dated.filter((e) => e.at != null && e.at >= start && e.at < end),
    ),
    previous = sum(previousEvents);
  const models = new Map<
    string,
    { events: typeof d.events; chats: Set<string>; missing: boolean }
  >();
  for (const session of sessions)
    for (const event of session.events) {
      const key = event.model || session.model || "Unreported",
        row = models.get(key) || {
          events: [],
          chats: new Set<string>(),
          missing: false,
        };
      row.events.push(event);
      row.chats.add(session.id);
      row.missing ||= Boolean(
        event.cache_unreported || session.cache_unreported,
      );
      models.set(key, row);
    }
  let cost = 0,
    pricedTokens = 0,
    pricedUpdates = 0;
  const unknown = new Set<string>();
  for (const session of sessions)
    for (const event of session.events) {
      const priced = eventPricing(
        event,
        session.model,
        session.provider,
        prices,
      );
      cost += priced.cost;
      pricedTokens += priced.pricedTokens;
      if (priced.pricedTokens > 0) pricedUpdates++;
      if (priced.unreported && eventTotal(event))
        unknown.add(event.model || session.model || "Unreported");
    }
  const maximum = Math.max(1, ...d.hours.flat());
  return (
    <div id="statsPage">
      <section className="metrics" aria-label="Statistical summary">
        {[
          [
            "Median update",
            d.median == null ? "Unreported" : compact(d.median),
            `${exact(d.events.length)} recorded usage updates`,
          ],
          [
            "90th percentile",
            d.p90 == null ? "Unreported" : compact(d.p90),
            "Tokens per usage update, interpolated",
          ],
          [
            "99th percentile",
            d.p99 == null ? "Unreported" : compact(d.p99),
            "Tokens per usage update, interpolated",
          ],
          [
            "Mean per chat",
            d.chats.length ? compact(total / d.chats.length) : "Unreported",
            `${d.chats.length} chats with positive usage`,
          ],
          [
            "Cache read share",
            d.cacheMissing ? "Unreported" : ratio(d.totals.cached, input),
            "Cache reads / all input tokens",
          ],
        ].map(([label, value, note]) => (
          <div className="metric" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
            <small>{note}</small>
          </div>
        ))}
      </section>
      <p className="stats-scope">
        {exact(total)} recorded tokens · {d.days.size} days with dated updates ·{" "}
        {d.events.length - d.dated.length} undated updates excluded from time
        charts. Statistics describe retained telemetry.
      </p>
      <div className="stats-layout">
        <Panel
          title="Daily usage"
          note="Recorded tokens by local calendar day."
        >
          <Line
            points={d.timeline.map(([key, value]) => [key, value.total])}
            label="Recorded tokens"
          />
        </Panel>
        <Panel
          title="Cumulative usage"
          note="Running total across the selected dated range."
        >
          <Line points={running} label="Cumulative tokens" />
        </Panel>
        <Panel
          title="Token composition"
          note="Reasoning is already included in output."
        >
          <Bars
            rows={(["input", "cached", "write", "output"] as const).map(
              (key) => [key, d.totals[key]],
            )}
            total={total}
          />
          <p className="stats-note">
            {exact(d.totals.reasoning)} recorded reasoning tokens.
            {d.cacheMissing ? " Cache breakdown is incomplete." : ""}
          </p>
        </Panel>
        <Panel
          title="Daily cache reuse"
          note="Unreported cache breakdowns remain gaps."
        >
          <Line
            points={d.timeline.map(([key, v]) => [
              key,
              v.cacheMissing || (!v.input && !v.cached && !v.write)
                ? null
                : (100 * v.cached) / (v.input + v.cached + v.write),
            ])}
            label="Cache read share"
            percentage
          />
        </Panel>
        <Panel
          title="Weekday and hour"
          note="Local time, selected recorded usage."
          wide
        >
          <div className="stats-heatmap-scroll">
            <div className="stats-heatmap">
              <span />
              {Array.from({ length: 24 }, (_, h) => (
                <span key={h}>
                  {h % 3 === 0 ? String(h).padStart(2, "0") : ""}
                </span>
              ))}
              {d.hours.map((row, index) => (
                <div key={index} style={{ display: "contents" }}>
                  <span>{weekdays[index]}</span>
                  {row.map((value, h) => (
                    <span
                      key={h}
                      className="stats-cell"
                      tabIndex={0}
                      style={
                        {
                          "--intensity": value
                            ? 0.18 + (0.82 * value) / maximum
                            : 0,
                        } as CSSProperties
                      }
                      aria-label={`${weekdays[index]} ${h}:00: ${exact(value)} tokens`}
                    >
                      <span>{compact(value)}</span>
                    </span>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </Panel>
        <Panel title="Usage by provider" note="Recorded tokens by tool.">
          <Ranking map={d.providers} />
        </Panel>
        <Panel
          title="Usage by model"
          note="Each update uses its recorded model or conversation fallback."
        >
          <Ranking map={d.models} />
        </Panel>
        <Panel
          title="Usage by project"
          note="Projects recorded on conversations."
        >
          <Ranking map={d.projects} />
        </Panel>
        <Panel title="Weekday usage" note="Totals across observed weekdays.">
          <Bars
            rows={d.weekdays.map((value, index) => [weekdays[index], value])}
          />
        </Panel>
        <Panel
          title="Update size distribution"
          note="Usage updates are not necessarily individual requests."
        >
          <Bars
            rows={d.distribution.map((value, index) => [
              ["0 to 1k", "1k to 10k", "10k to 100k", "100k to 1M", "1M+"][
                index
              ],
              value,
            ])}
          />
        </Panel>
        <Panel
          title="Conversation concentration"
          note={`${ratio(
            d.chats.slice(0, 5).reduce((n, s) => n + s.scope.total, 0),
            total,
          )} of tokens in the five largest chats.`}
        >
          <Bars
            rows={d.chats
              .slice(0, 8)
              .map((s) => [s.title || s.session_id, s.scope.total])}
            total={total}
          />
        </Panel>
        <Panel
          title="Period comparison"
          note="Compare immediately preceding intervals of equal elapsed duration."
        >
          {start && end > start ? (
            <Facts
              rows={[
                ["Current interval", `${date(start)} to ${date(end)}`],
                [
                  "Previous interval",
                  `${date(start - (end - start))} to ${date(start)}`,
                ],
                ["Current dated tokens", fmt(current.total)],
                [
                  "Previous dated tokens",
                  previousEvents.length
                    ? fmt(previous.total)
                    : "No recorded updates",
                ],
                [
                  "Change",
                  previous.total
                    ? `${((current.total / previous.total - 1) * 100).toFixed(1)}%`
                    : "Unreported",
                ],
                [
                  "Absolute difference",
                  previousEvents.length
                    ? fmt(current.total - previous.total)
                    : "Unreported",
                ],
              ]}
            />
          ) : (
            <p className="stats-note">
              Choose a finite time range to compare intervals.
            </p>
          )}
        </Panel>
        <Panel title="Usage peaks" note="Peaks describe the retained logs.">
          <Facts
            rows={[
              [
                "Highest-volume day",
                peaks.length
                  ? `${peaks[0][0]} · ${fmt(peaks[0][1].total)}`
                  : "Unreported",
              ],
              [
                "Highest-volume hour",
                d.dated.length
                  ? `${hourPeak[0]} · ${fmt(hourPeak[1])}`
                  : "Unreported",
              ],
              ["Largest usage update", fmt(d.sizes[d.sizes.length - 1])],
              [
                "Largest chat",
                d.chats[0]
                  ? `${d.chats[0].title} · ${fmt(d.chats[0].scope.total)}`
                  : "Unreported",
              ],
              [
                "Top 10% of chats",
                total
                  ? `${ratio(
                      d.chats
                        .slice(0, topCount)
                        .reduce((n, s) => n + s.scope.total, 0),
                      total,
                    )} of tokens (${topCount} chats, rounded up)`
                  : "Unreported",
              ],
              [
                "Recorded reasoning / output",
                ratio(d.totals.reasoning, d.totals.output),
              ],
            ]}
          />
        </Panel>
        <Panel
          title="Daily variability"
          note="Calendar days inside the observed span, including gaps."
        >
          <Summary values={d.timeline.map(([, v]) => v.total)} />
        </Panel>
        <Panel
          title="Update size statistics"
          note="Interpolated percentiles; population standard deviation."
        >
          <Summary values={d.sizes} />
        </Panel>
        <Panel
          title="Conversation size statistics"
          note="Chats with positive usage after grouping."
        >
          <Summary values={d.chats.map((s) => s.scope.total)} />
        </Panel>
        <Panel
          title="Data coverage"
          note="Coverage alone cannot establish complete accounting."
        >
          <Facts
            rows={[
              ["Selected chats", fmt(sessions.length)],
              ["Chats with positive usage", fmt(d.chats.length)],
              [
                "Chats with unreported usage",
                fmt(
                  sessions.filter((s) => s.usage_source === "unavailable")
                    .length,
                ),
              ],
              ["Dated updates", `${d.dated.length} / ${d.events.length}`],
              ["Dated token share", ratio(sum(d.dated).total, total)],
              [
                "Updates missing cache breakdown",
                fmt(
                  sessions.reduce(
                    (n, s) =>
                      n +
                      s.events.filter(
                        (e) => e.cache_unreported || s.cache_unreported,
                      ).length,
                    0,
                  ),
                ),
              ],
              [
                "Updates using conversation model fallback",
                fmt(d.events.filter((e) => !e.model).length),
              ],
              [
                "First dated update",
                d.dated.length
                  ? date(d.dated.reduce((n, e) => Math.min(n, e.at!), Infinity))
                  : "Unreported",
              ],
              [
                "Last dated update",
                d.dated.length
                  ? date(
                      d.dated.reduce((n, e) => Math.max(n, e.at!), -Infinity),
                    )
                  : "Unreported",
              ],
            ]}
          />
        </Panel>
        <Panel
          title="Daily update count"
          note="Recorded updates, not requests."
        >
          <Line
            points={d.timeline.map(([key, v]) => [key, v.count])}
            label="Usage updates"
          />
        </Panel>
        <Panel
          title="Mean update size"
          note="Days without updates remain gaps."
        >
          <Line
            points={d.timeline.map(([key, v]) => [
              key,
              v.count ? v.total / v.count : null,
            ])}
            label="Mean tokens per update"
          />
        </Panel>
        <Panel
          title="Daily output share"
          note="Reasoning is included in output."
        >
          <Line
            points={d.timeline.map(([key, v]) => [
              key,
              v.total ? (100 * v.output) / v.total : null,
            ])}
            label="Output share"
            percentage
          />
        </Panel>
        <Panel
          title="Mean usage by weekday"
          note="Days inside the observed span; missing weekdays omitted."
        >
          <Bars
            rows={d.weekdays.flatMap((v, i) =>
              weekdayCounts[i]
                ? [
                    [
                      `${weekdays[i]} (${weekdayCounts[i]} days)`,
                      v / weekdayCounts[i],
                    ] as [string, number],
                  ]
                : [],
            )}
          />
        </Panel>
        <Panel
          title="Cumulative conversation share"
          note="Positive-usage chats ranked largest first, rounded up."
        >
          <Line
            points={d.chats.length ? concentration : []}
            label="Share of recorded tokens"
            percentage
            xLabel="Share of chats"
          />
        </Panel>
        <Panel
          title="Estimated API list cost"
          note="List-price equivalent for priced usage, not a subscription bill."
        >
          <Facts
            rows={[
              [
                "Estimated API list cost",
                pricedUpdates
                  ? `${money(cost)}${unknown.size ? "*" : ""}`
                  : "Unreported",
              ],
              ["Priced token coverage", ratio(pricedTokens, total)],
              ["Priced updates", `${pricedUpdates} / ${d.events.length}`],
              [
                "Models with unpriced components",
                unknown.size
                  ? [...unknown].join(", ")
                  : "None in selected usage",
              ],
            ]}
          />
        </Panel>
        <Panel
          title="Model details"
          note="Per-update model attribution with conversation fallback."
          wide
        >
          <div className="stats-detail-table">
            <table>
              <thead>
                <tr>
                  {[
                    "Model",
                    "Tokens",
                    "Updates",
                    "Chats",
                    "Mean update",
                    "Output share",
                    "Cache share",
                  ].map((h) => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...models]
                  .sort(
                    (a, b) => sum(b[1].events).total - sum(a[1].events).total,
                  )
                  .map(([name, row]) => {
                    const t = sum(row.events);
                    return (
                      <tr key={name}>
                        <td>{name}</td>
                        <td>{exact(t.total)}</td>
                        <td>{row.events.length}</td>
                        <td>{row.chats.size}</td>
                        <td>{fmt(t.total / row.events.length)}</td>
                        <td>{ratio(t.output, t.total)}</td>
                        <td>
                          {row.missing
                            ? "Unreported"
                            : ratio(t.cached, t.input + t.cached + t.write)}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>
  );
}
