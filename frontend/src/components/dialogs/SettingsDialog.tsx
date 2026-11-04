import { useState } from "react";
import { useAppStore } from "../../store/useAppStore";
import { saved } from "../../utils/storage";
import { applyTheme, type Theme } from "../../utils/theme";
import { alertsEnabled, toggleAlerts } from "../../utils/notifications";
import { Dialog } from "./Dialog";
export function SettingsDialog() {
  const s = useAppStore(),
    [theme, setTheme] = useState<Theme>(() => {
      try {
        const raw = localStorage.getItem("to.theme");
        if (raw === "dark" || raw === "light" || raw === "auto") return raw;
      } catch {
        /* Use defaults. */
      }
      return saved.get<Theme>("theme", "auto");
    }),
    [range, setRange] = useState(
      saved.get("dashboardDefaults", { range: "today", agents: true }).range,
    ),
    [agents, setAgents] = useState(
      saved.get("dashboardDefaults", { range: "today", agents: true }).agents,
    ),
    [alerts, setAlerts] = useState(alertsEnabled()),
    [budget, setBudget] = useState(
      String(saved.get<number | null>("dailyBudget", null) || ""),
    ),
    [message, setMessage] = useState("");
  return (
    <Dialog title="Settings" onClose={() => s.setDialog(null)}>
      <section className="settings-section">
        <h3>Appearance</h3>
        <div className="theme-options">
          {(["auto", "light", "dark"] as const).map((v) => (
            <label key={v}>
              <input
                type="radio"
                name="themePreference"
                value={v}
                checked={theme === v}
                onChange={() => {
                  setTheme(v);
                  applyTheme(v);
                }}
              />{" "}
              {v === "auto" ? "System" : v === "light" ? "Light" : "Dark"}
            </label>
          ))}
        </div>
      </section>
      <section className="settings-section">
        <h3>Tracking &amp; limits</h3>
        <div className="settings-links">
          <button className="button" onClick={() => s.setDialog("providers")}>
            Providers
          </button>
          <button className="button" onClick={() => s.setDialog("limits")}>
            Limit controls &amp; history
          </button>
          <button className="button" onClick={() => s.setDialog("sources")}>
            Data sources &amp; accuracy
          </button>
        </div>
        <p className="insight-note">
          Warnings, hard thresholds, and weekly reserves apply across the app
          through Limit controls.
        </p>
      </section>
      <section className="settings-section">
        <h3>Notifications</h3>
        <button
          className="button"
          disabled={typeof Notification === "undefined"}
          onClick={() => {
            void toggleAlerts().then((enabled) => {
              setAlerts(enabled);
              if (!enabled)
                setMessage(
                  "Alerts are off. Browser permission is required to enable them.",
                );
            });
          }}
        >
          Alerts {alerts ? "on" : "off"}
        </button>
        <p className="insight-note">
          Desktop alerts for usage thresholds, resets, context pressure and
          daily budgets. Choose reset alerts under Limit controls.
        </p>
      </section>
      <section className="settings-section">
        <h3>Dashboard defaults</h3>
        <label className="settings-field">
          Time range
          <select value={range} onChange={(e) => setRange(e.target.value)}>
            <option value="today">Today</option>
            <option value="48h">Last 48 hours</option>
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
            <option value="all">All retained logs</option>
          </select>
        </label>
        <label className="update-check">
          <input
            type="checkbox"
            checked={agents}
            onChange={(e) => setAgents(e.target.checked)}
          />{" "}
          Include subagents by default
        </label>
        <label className="settings-field">
          Daily token budget
          <input
            type="number"
            min="1"
            max="10000000000000"
            step="1"
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
            placeholder="Suggested budget"
          />
        </label>
        <button
          className="button"
          onClick={() => {
            if (
              budget &&
              (!Number.isInteger(Number(budget)) ||
                Number(budget) < 1 ||
                Number(budget) > 1e13)
            ) {
              setMessage("Enter a whole number from 1 to 10 trillion tokens.");
              return;
            }
            saved.set("dashboardDefaults", { range, agents });
            saved.set("dailyBudget", budget ? Number(budget) : null);
            s.setRange(range);
            s.setAgentsIncluded(agents);
            setMessage("Dashboard defaults saved.");
          }}
        >
          Save dashboard defaults
        </button>
        <p className="update-progress" role="status">
          {message}
        </p>
      </section>
    </Dialog>
  );
}
