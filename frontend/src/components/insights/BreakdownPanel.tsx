import { useState } from "react";
import type { ScopedSession } from "../../types/session";
import type { Pricing } from "../../types/snapshot";
import { sum, eventTotal, exact, compact, percent } from "../../utils/tokens";
import { eventPricing, money } from "../../utils/cost";
import { saved } from "../../utils/storage";
import { useAppStore } from "../../store/useAppStore";
export function BreakdownPanel({
  sessions,
  pricing,
}: {
  sessions: ScopedSession[];
  pricing?: Pricing;
}) {
  const [by, setBy] = useState(saved.get("breakdownBy", "model")),
    [all, setAll] = useState(false),
    setSearch = useAppStore((s) => s.setSearch),
    setSelected = useAppStore((s) => s.setSelected),
    groups = new Map<
      string,
      {
        name: string;
        input: number;
        cached: number;
        write: number;
        fresh: number;
        output: number;
        total: number;
        cost: number;
        priced: boolean;
        unreported: boolean;
      }
    >();
  for (const s of sessions)
    for (const e of s.events) {
      const name =
          by === "model"
            ? e.model || s.model || "Unreported"
            : s.project || "Unknown project",
        g = groups.get(name) || {
          name,
          input: 0,
          cached: 0,
          write: 0,
          fresh: 0,
          output: 0,
          total: 0,
          cost: 0,
          priced: false,
          unreported: false,
        };
      g.input += (e.input || 0) + (e.cached || 0) + (e.write || 0);
      g.cached += e.cached || 0;
      g.fresh += e.input || 0;
      g.write += e.write || 0;
      g.output += e.output || 0;
      g.total += eventTotal(e);
      const c = eventPricing(e, s.model, s.provider, pricing);
      g.cost += c.cost;
      g.unreported ||= c.unreported;
      if (c.pricedTokens > 0) g.priced = true;
      groups.set(name, g);
    }
  const rows = [...groups.values()].sort((a, b) => b.total - a.total),
    grand = rows.reduce((n, r) => n + r.total, 0),
    top = Math.max(1, ...rows.map((r) => r.total)),
    low = sessions
      .map((s) => ({
        s,
        input: s.scope.input + s.scope.cached + s.scope.write,
      }))
      .filter(
        (x) => x.input >= 100000 && !x.s.events.some((e) => e.cache_unreported),
      )
      .sort(
        (a, b) =>
          percent(a.s.scope.cached, a.input) -
          percent(b.s.scope.cached, b.input),
      )[0];
  return (
    <section className="panel" aria-label="Breakdown by model or project">
      <div className="panel-heading">
        <div>
          <h2>Breakdown</h2>
          <p>
            Tokens in the selected range. Click a name to see input and output.
          </p>
        </div>
        <div className="segmented small">
          {["model", "project"].map((k) => (
            <button
              key={k}
              className={k === by ? "selected" : ""}
              onClick={() => {
                setBy(k);
                saved.set("breakdownBy", k);
              }}
            >
              By {k}
            </button>
          ))}
        </div>
      </div>
      <div className="breakdown-legend">
        <span>
          <i className="swatch input" />
          Input incl. cache
        </span>
        <span>
          <i className="swatch output" />
          Output
        </span>
      </div>
      <div className="breakdown-table">
        {(all ? rows : rows.slice(0, 8)).map((r) => (
          <details key={`${by}:${r.name}`} className="breakdown-group">
            <summary className="breakdown-item">
              <span className="breakdown-name">{r.name}</span>
              <span
                className="breakdown-meter"
                title={`Input ${exact(r.input)} / output ${exact(r.output)}`}
              >
                <span
                  className="fill"
                  style={{ width: `${percent(r.total, top)}%` }}
                >
                  <i className="in" style={{ flex: r.input }} />
                  <i
                    className="out"
                    style={{ flex: Math.max(r.output, r.total * 0.01) }}
                  />
                </span>
              </span>
              <strong title={exact(r.total)}>{compact(r.total)}</strong>
              <span>{percent(r.total, grand).toFixed(1)}%</span>
              <span>{percent(r.cached, r.input).toFixed(0)}% cached</span>
            </summary>
            <div className="breakdown-detail">
              {[
                ["Fresh input", r.fresh],
                ["Cache read", r.cached],
                ["Cache write", r.write],
                ["Output", r.output],
              ].map(([label, n]) => (
                <div key={label}>
                  <span>{label}</span>
                  <strong>{compact(Number(n))}</strong>
                </div>
              ))}
              <div>
                <span>Est. cost</span>
                <strong>{money(r.cost) + (r.unreported ? "*" : "")}</strong>
              </div>
              <button className="link" onClick={() => setSearch(r.name)}>
                Filter conversations to {r.name}
              </button>
            </div>
          </details>
        ))}
        {rows.length > 8 && (
          <button className="link" onClick={() => setAll(!all)}>
            {all ? "Show fewer" : `Other (${rows.length - 8})`}
          </button>
        )}
        {!rows.length && (
          <div className="empty-state">No usage in this range.</div>
        )}
      </div>
      {low && (
        <p className="insight-note">
          Lowest cache reuse:{" "}
          <button className="link" onClick={() => setSelected(low.s.id)}>
            {low.s.title}
          </button>{" "}
          at {percent(low.s.scope.cached, low.input).toFixed(0)}% of input from
          cache.
        </p>
      )}
    </section>
  );
}
