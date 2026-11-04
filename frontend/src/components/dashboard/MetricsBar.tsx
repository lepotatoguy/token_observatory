import type { ScopedSession } from "../../types/session";
import type { Pricing } from "../../types/snapshot";
import { sum, compact, exact } from "../../utils/tokens";
import { costOf, money } from "../../utils/cost";
export function MetricsBar({
  sessions,
  pricing,
}: {
  sessions: ScopedSession[];
  pricing?: Pricing;
}) {
  const events = sessions.flatMap((s) => s.events),
    totals = sum(events),
    input = totals.input + totals.cached + totals.write,
    missing = sessions.filter((s) => s.usage_source === "unavailable").length,
    cacheMissing = events.some((e) => e.cache_unreported),
    cost = costOf(sessions, pricing);
  const cards = [
    [
      "Recorded tokens",
      compact(totals.total),
      `${exact(sessions.length)} chats · ${missing} unreported`,
      exact(totals.total),
    ],
    [
      "Input tokens",
      compact(input),
      "Fresh input + cache reads + writes",
      exact(input),
    ],
    [
      "Output tokens",
      compact(totals.output),
      `${exact(totals.reasoning)} recorded reasoning tokens included`,
      exact(totals.output),
    ],
    [
      "Cache read share",
      cacheMissing
        ? "Unreported"
        : `${(input ? (100 * totals.cached) / input : 0).toFixed(1)}%`,
      cacheMissing
        ? "Some chats do not record cache breakdown."
        : `${compact(totals.cached)} input tokens served from cache`,
      "",
    ],
    [
      "Estimated cost",
      money(cost.cost) + (cost.unpriced.length ? "*" : ""),
      cost.unpriced.length
        ? `${cost.unpriced.length} models have unreported cost components`
        : "At list API prices",
      cost.unpriced.length
        ? `Unpriced: ${cost.unpriced.join(", ")}`
        : "Published per-token prices",
    ],
  ];
  return (
    <section className="metrics" aria-label="Token totals">
      {cards.map(([label, value, note, title]) => (
        <div className="metric" key={label}>
          <span>{label}</span>
          <strong title={title}>{value}</strong>
          <small>{note}</small>
        </div>
      ))}
    </section>
  );
}
