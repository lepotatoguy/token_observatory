import { useState, useEffect } from "react";
import type { Snapshot } from "../../types/snapshot";
import type { ScopedSession } from "../../types/session";
import { useAppStore } from "../../store/useAppStore";
import { useRefresh } from "../../hooks/useUsage";
import { providerName, providerIcon } from "../../utils/tokens";
import { dayKey, dayLabel } from "../../utils/time";
import { csv, download, buildJsonPayload } from "../../utils/export";
import { visibleSessions } from "../dashboard/ConversationTable";
import { applyTheme } from "../../utils/theme";
export function Header({ error }: { error?: Error | null }) {
  const { paused, setPaused, page, setDialog, historyDay } = useAppStore(),
    refresh = useRefresh(),
    [dark, setDark] = useState(
      () => document.documentElement.dataset.theme === "dark",
    );
  useEffect(() => {
    const sync = () =>
      setDark(document.documentElement.dataset.theme === "dark");
    window.addEventListener("theme-change", sync);
    return () => window.removeEventListener("theme-change", sync);
  }, []);
  return (
    <header>
      <div className="breadcrumb">
        Workspace <span>/</span> {page === "overview" ? "Overview" : "Stats"}
      </div>
      <div className="connection">
        <span className={`tiny-dot${error ? " bad" : ""}`} />
        <span role="status">
          {error ? error.message : paused ? "Paused" : "Connected locally"}
        </span>
        <button
          className="quiet"
          title="Switch theme"
          aria-label={`Switch to ${dark ? "light" : "dark"} theme`}
          onClick={() => {
            applyTheme(dark ? "light" : "dark");
            setDark(!dark);
          }}
        >
          {dark ? "☀" : "☾"}
        </button>
        <button
          className="quiet limit-controls-mobile"
          onClick={() => setDialog("settings")}
        >
          Settings
        </button>
        <button
          className="quiet"
          disabled={refresh.isPending || !!historyDay}
          title="Rescan logs and check current usage limits"
          onClick={() => refresh.mutate()}
        >
          {refresh.isPending ? "Refreshing…" : "Refresh"}
        </button>
        <button className="quiet" onClick={() => setPaused(!paused)}>
          {paused ? "Resume" : "Pause"}
        </button>
      </div>
      {refresh.error && <p role="alert">{refresh.error.message}</p>}
    </header>
  );
}
export function PageHeading({
  snapshot,
  sessions,
}: {
  snapshot: Snapshot;
  sessions: ScopedSession[];
}) {
  const state = useAppStore(),
    page = state.page,
    search = page === "stats" ? "" : state.search,
    exported = visibleSessions(
      sessions,
      search,
      state.sort,
      state.sortDirection,
    );
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">EVERY TOKEN, ACCOUNTED FOR</div>
        <h1>
          {page === "overview" ? "Usage overview" : "Token statistics"}
          <span className="heading-dot">.</span>
        </h1>
        <p>
          {page === "overview"
            ? "Follow token consumption across your coding conversations."
            : "Explore your recorded token usage and variability."}
        </p>
      </div>
      <div className="export-actions">
        <button
          className="button"
          onClick={() =>
            download(
              `token-observatory-${dayKey(snapshot.at)}.json`,
              "application/json",
              JSON.stringify(
                buildJsonPayload(snapshot, exported, {
                  ...state,
                  search,
                  now: state.historyDay ? snapshot.at : Date.now() / 1000,
                }),
                null,
                2,
              ),
            )
          }
        >
          ↓ <span>Export JSON</span>
        </button>
        <button
          className="button"
          onClick={() =>
            download(
              `token-observatory-${dayKey(snapshot.at)}.csv`,
              "text/csv;charset=utf-8",
              csv(exported),
            )
          }
        >
          ↓ <span>Export CSV</span>
        </button>
      </div>
    </div>
  );
}
export function FilterBar({ snapshot }: { snapshot: Snapshot }) {
  const s = useAppStore(),
    providers = [
      ...new Set([
        ...(snapshot.providers?.enabled || ["claude", "codex"]),
        ...snapshot.sessions.map((chat) => chat.provider),
      ]),
    ];
  return (
    <div className="toolbar">
      <div className="segmented" aria-label="Provider filter">
        {["all", ...providers].map((p) => (
          <button
            key={p}
            className={s.provider === p ? "selected" : ""}
            onClick={() => s.setProvider(p)}
          >
            {p === "all"
              ? "All providers"
              : `${providerIcon(p)} ${providerName(p)}`}
          </button>
        ))}
      </div>
      <div className="toolbar-right">
        <label className="agent-toggle">
          <input
            type="checkbox"
            checked={s.agentsIncluded}
            onChange={(e) => s.setAgentsIncluded(e.target.checked)}
          />{" "}
          Include subagents
        </label>
        {s.day && (
          <button
            className="day-chip"
            aria-label="Clear day filter"
            onClick={() => s.setDay(null)}
          >
            {dayLabel(s.day)} ✕
          </button>
        )}
        <label className="sr-only" htmlFor="history">
          Saved history
        </label>
        <select
          id="history"
          value={s.historyDay}
          onChange={(e) => s.setHistoryDay(e.target.value)}
        >
          <option value="">Live</option>
          {snapshot.archive?.dates.map((day) => (
            <option key={day} value={day}>
              Saved · {day}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="range">
          Time range
        </label>
        <select
          id="range"
          value={s.range}
          onChange={(e) => s.setRange(e.target.value)}
        >
          <option value="today">Today</option>
          <option value="48h">Last 48 hours</option>
          <option value="7d">Last 7 days</option>
          <option value="30d">Last 30 days</option>
          <option value="all">All retained logs</option>
        </select>
      </div>
    </div>
  );
}
