import { useEffect, useRef } from "react";
import { useUsage } from "./hooks/useUsage";
import { usePricing } from "./hooks/usePricing";
import { useUpdates } from "./hooks/useUpdates";
import { useAppStore } from "./store/useAppStore";
import { Sidebar } from "./components/layout/Sidebar";
import { Header, PageHeading, FilterBar } from "./components/layout/Header";
import { MetricsBar } from "./components/dashboard/MetricsBar";
import { ActivityChart } from "./components/dashboard/ActivityChart";
import {
  ConversationTable,
  visibleSessions,
} from "./components/dashboard/ConversationTable";
import { Inspector } from "./components/dashboard/Inspector";
import { LimitsPanel } from "./components/insights/LimitsPanel";
import { BudgetPanel } from "./components/insights/BudgetPanel";
import { BreakdownPanel } from "./components/insights/BreakdownPanel";
import { TrendsPanel } from "./components/insights/TrendsPanel";
import { PressureBanner } from "./components/shared/PressureBanner";
import { SettingsDialog } from "./components/dialogs/SettingsDialog";
import { ProvidersDialog } from "./components/dialogs/ProvidersDialog";
import { LimitControlsDialog } from "./components/dialogs/LimitControlsDialog";
import { SourcesDialog } from "./components/dialogs/SourcesDialog";
import { UpdateDialog } from "./components/dialogs/UpdateDialog";
import StatsPage from "./components/stats/StatsPage";
import { scoped } from "./utils/conversations";
import { date } from "./utils/time";
import type { Archive } from "./types/snapshot";
export default function App() {
  const usage = useUsage(),
    pricing = usePricing(),
    updates = useUpdates(),
    s = useAppStore(),
    snapshot = usage.data,
    archive = useRef<Archive>(),
    setupShown = useRef(false),
    updateShown = useRef<string | null>(null);
  if (snapshot?.archive) archive.current = snapshot.archive;
  useEffect(() => {
    const change = () =>
      s.setPage(location.hash === "#stats" ? "stats" : "overview");
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, [s.setPage]);
  useEffect(() => {
    if (
      snapshot?.providers &&
      !snapshot.providers.setup_done &&
      !s.historyDay &&
      !setupShown.current
    ) {
      setupShown.current = true;
      s.setDialog("providers");
    }
  }, [snapshot, s.historyDay, s.setDialog]);
  useEffect(() => {
    if (
      updates.data?.prompt &&
      updates.data.latest &&
      updateShown.current !== updates.data.latest.version &&
      !s.dialog
    ) {
      updateShown.current = updates.data.latest.version;
      s.setDialog("update");
    }
  }, [updates.data, s.dialog, s.setDialog]);
  if (!snapshot)
    return (
      <>
        <Sidebar />
        <main>
          <Header error={usage.error} />
          <div className="page">
            <div className="empty-state">
              {usage.error
                ? `Could not read local telemetry: ${usage.error.message}`
                : "Reading recorded telemetry…"}
            </div>
            <button
              className="button"
              onClick={() => {
                void usage.refetch();
              }}
            >
              Retry
            </button>
          </div>
          {s.historyDay && (
            <button className="button" onClick={() => s.setHistoryDay("")}>
              Return to Live
            </button>
          )}
        </main>
      </>
    );
  const current = { ...snapshot, archive: snapshot.archive || archive.current },
    now = s.historyDay ? snapshot.at : Date.now() / 1000,
    sessions = scoped(snapshot.sessions, {
      provider: s.provider,
      agentsIncluded: s.agentsIncluded,
      range: s.range,
      day: s.day,
      now,
    }),
    visible = visibleSessions(sessions, s.search, s.sort, s.sortDirection),
    selected = visible.find((chat) => chat.id === s.selected),
    errors = snapshot.sessions.reduce(
      (n, chat) => n + (chat.parse_errors || 0),
      0,
    ),
    warnings = [
      ...(snapshot.warnings || []),
      ...(errors ? [`${errors} malformed log records skipped.`] : []),
      ...(s.historyDay &&
      snapshot.sessions.some(
        (chat) => chat.provider === "codex" && chat.accounting_version !== 2,
      )
        ? [
            "Legacy Codex rows retained: log segments may overlap; per-response detail was not saved.",
          ]
        : []),
    ];
  return (
    <>
      <Sidebar />
      <main>
        <Header error={usage.error} />
        <div className="page">
          <PageHeading snapshot={current} sessions={sessions} />
          <FilterBar snapshot={current} />
          {warnings.length > 0 && (
            <div className="warning">{warnings.join(" · ")}</div>
          )}
          <PressureBanner snapshot={snapshot} now={now} />
          <nav className="mobile-page-nav" aria-label="Pages">
            <a href="#overview" onClick={() => s.setPage("overview")}>
              Overview
            </a>
            <a href="#stats" onClick={() => s.setPage("stats")}>
              Stats
            </a>
          </nav>
          {s.page === "overview" ? (
            <div>
              <MetricsBar sessions={sessions} pricing={pricing.data} />
              <section className="insight-row" aria-label="Limits and budget">
                <LimitsPanel snapshot={snapshot} now={now} />
                <BudgetPanel
                  key={s.dialog === "settings" ? "editing" : "view"}
                  snapshot={snapshot}
                  now={now}
                />
              </section>
              <section className="panel activity-panel">
                <div className="panel-heading">
                  <div>
                    <h2>Token activity</h2>
                    <p>
                      {sessions.reduce(
                        (n, chat) =>
                          n + chat.events.filter((e) => e.at !== null).length,
                        0,
                      )}{" "}
                      timestamped usage updates in selected range
                    </p>
                  </div>
                  <div className="chart-legend">
                    <span>
                      <i className="swatch input" />
                      Input incl. cache
                    </span>
                    <span>
                      <i className="swatch output" />
                      Output
                    </span>
                  </div>
                </div>
                <ActivityChart
                  events={sessions.flatMap((chat) => chat.events)}
                  now={now}
                />
              </section>
              <div className="insight-grid">
                <BreakdownPanel sessions={sessions} pricing={pricing.data} />
                <TrendsPanel snapshot={snapshot} now={now} />
              </div>
              <div className="lower-grid">
                <ConversationTable sessions={sessions} now={now} />
                <Inspector session={selected} sessions={visible} now={now} />
              </div>
            </div>
          ) : (
            <StatsPage
              sessions={sessions}
              snapshot={snapshot}
              now={now}
              range={s.range}
              day={s.day}
              provider={s.provider}
              agentsIncluded={s.agentsIncluded}
              prices={pricing.data}
            />
          )}
          <footer>
            <span className="collector-status">
              <span>
                <i className="tiny-dot" /> Read-only local collector · checks
                every 2 seconds
              </span>
              <span className="json-status" role="status">
                {s.historyDay
                  ? `Viewing saved history for ${s.historyDay}. Time filters use its capture time.`
                  : current.archive?.error ||
                    `JSON auto-save: ${current.archive?.saved_at ? date(current.archive.saved_at) : "first capture pending"} · Latest capture retained for each day`}
              </span>
            </span>
            <span className="footer-right">
              {updates.data &&
                updates.data.checks !== false &&
                (updates.data.latest || !updates.data.notify) && (
                  <button
                    className="update-notice"
                    onClick={() => s.setDialog("update")}
                  >
                    {updates.data.notify
                      ? `Version ${updates.data.latest?.version} available · Update`
                      : "Update notifications off · Settings"}
                  </button>
                )}
              <span>
                {s.historyDay ? "Snapshot captured" : "Last scan"}{" "}
                {date(snapshot.at)}
              </span>
            </span>
          </footer>
        </div>
      </main>
      {s.dialog === "settings" && <SettingsDialog />}
      {s.dialog === "providers" && (
        <ProvidersDialog firstRun={!snapshot.providers?.setup_done} />
      )}
      {s.dialog === "limits" && (
        <LimitControlsDialog
          providers={["claude", "codex", "minimax"].filter((p) =>
            snapshot.providers?.enabled.includes(p),
          )}
        />
      )}
      {s.dialog === "sources" && <SourcesDialog snapshot={current} />}
      {s.dialog === "update" && <UpdateDialog />}
    </>
  );
}
