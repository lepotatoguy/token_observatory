import { useEffect, useState } from "react";
import { useLimitControls } from "../../hooks/useLimitControls";
import { useAppStore } from "../../store/useAppStore";
import type { LimitSettings, LimitPreference } from "../../types/limits";
import { providerName } from "../../utils/tokens";
import { date } from "../../utils/time";
import { alertsEnabled, toggleAlerts } from "../../utils/notifications";
import { Dialog } from "./Dialog";
const names = {
  warn: "Warning (% used)",
  hard: "5-hour hard limit (% used)",
  weekly_reserve: "Weekly reserve (% remaining)",
};
const defaults: LimitPreference = { warn: 80, hard: 95, weekly_reserve: 3 };
export function LimitControlsDialog({ providers }: { providers: string[] }) {
  const { data, error, save } = useLimitControls(),
    close = useAppStore((s) => s.setDialog),
    [settings, setSettings] = useState<LimitSettings>({
      reset_notifications: false,
    }),
    [message, setMessage] = useState(""),
    [alerts, setAlerts] = useState(alertsEnabled());
  useEffect(() => {
    if (data) setSettings(data.settings);
  }, [data]);
  function change(p: string, key: keyof LimitPreference, v: number | null) {
    setSettings((s) => ({
      ...s,
      [p]: {
        ...(typeof s[p] === "object"
          ? s[p]
          : { warn: null, hard: null, weekly_reserve: null }),
        [key]: v,
      },
    }));
  }
  return (
    <Dialog title="Limit controls" onClose={() => close(null)}>
      <p className="insight-note">
        Enable warnings, a 5-hour hard limit, and a weekly reserve independently
        for each provider. A 3% weekly reserve stops at 97% used. Warnings keep
        work going. Hard limits block supported hook events until reset or fresh
        usage falls below the threshold. Install or update conversation hooks to
        enforce them. An in-flight request can overshoot before the next check.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          for (const p of providers) {
            const pref = settings[p];
            if (typeof pref !== "object" || !pref) continue;
            for (const key of Object.keys(names) as (keyof LimitPreference)[]) {
              const v = pref[key];
              if (
                v != null &&
                (!Number.isFinite(v) ||
                  v < (key === "weekly_reserve" ? 0 : 1) ||
                  v > 100)
              ) {
                setMessage(
                  "Thresholds must be from 1 to 100%; weekly reserve can also be 0%.",
                );
                return;
              }
            }
            if (
              pref.warn !== null &&
              pref.hard !== null &&
              pref.warn > pref.hard
            ) {
              setMessage("Warning threshold must not exceed the hard limit.");
              return;
            }
          }
          save.mutate(settings, {
            onSuccess: () =>
              setMessage(
                "Saved. Applies to new hook events in this chat and other chats.",
              ),
          });
        }}
      >
        {providers.map((p) => {
          const pref = settings[p];
          return (
            <fieldset className="limit-preferences" key={p}>
              <legend>{providerName(p)}</legend>
              {(Object.keys(names) as (keyof LimitPreference)[]).map((key) => {
                const value = typeof pref === "object" ? pref[key] : null;
                return (
                  <div className="limit-action" key={key}>
                    <label>
                      <input
                        type="checkbox"
                        checked={value != null}
                        onChange={(e) =>
                          change(
                            p,
                            key,
                            e.target.checked ? defaults[key] : null,
                          )
                        }
                      />{" "}
                      {names[key]}
                    </label>
                    <label className="threshold-field">
                      <input
                        type="number"
                        min={key === "weekly_reserve" ? 0 : 1}
                        max="100"
                        step="any"
                        required
                        disabled={value == null}
                        aria-label={`${providerName(p)} ${names[key]}`}
                        value={value ?? defaults[key] ?? ""}
                        onChange={(e) => change(p, key, Number(e.target.value))}
                      />
                      <span>%</span>
                    </label>
                  </div>
                );
              })}
            </fieldset>
          );
        })}
        <label className="update-check">
          <input
            type="checkbox"
            checked={settings.reset_notifications}
            onChange={(e) =>
              setSettings((s) => ({
                ...s,
                reset_notifications: e.target.checked,
              }))
            }
          />{" "}
          Notify when a usage window resets
        </label>
        <p className="insight-note">
          Desktop notifications need Alerts on and this dashboard open. Paused
          work can continue in the same chat after reset. An idle chat may need
          a message to run again.
        </p>
        <div className="update-actions">
          <button
            type="button"
            className="button"
            disabled={typeof Notification === "undefined"}
            onClick={() => {
              void toggleAlerts().then(setAlerts);
            }}
          >
            {alerts ? "Desktop alerts on" : "Enable desktop alerts"}
          </button>
          <button className="button primary" disabled={!data || save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
      <p role="status" className="update-progress">
        {message || error?.message || save.error?.message}
      </p>
      <details open>
        <summary>Event history · last 30 days</summary>
        <p className="insight-note">
          Up to 1,000 recent events; history file capped at 256 KiB. No chat
          content is stored. Older entries may be removed sooner when capped.
        </p>
        {data?.events.length ? (
          <div className="limit-event-history">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Limit</th>
                  <th>Event</th>
                </tr>
              </thead>
              <tbody>
                {data.events.map((event, i) => (
                  <tr key={i}>
                    <td>{date(event.at)}</td>
                    <td>
                      {event.provider
                        ? `${providerName(event.provider)} · ${event.limit || ""}`
                        : "All providers"}
                    </td>
                    <td>
                      {(
                        {
                          threshold: "Threshold reached",
                          exhausted: "Limit exhausted",
                          pause: "Pause requested",
                          reset: "Window reset",
                          settings: "Limit settings changed",
                        } as Record<string, string>
                      )[event.type] || event.type}
                      {event.used !== undefined ? ` · ${event.used}%` : ""}
                      {event.mode
                        ? ` · ${event.mode === "warn" ? "Warn" : "Hard limit"}`
                        : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="insight-note">No limit events recorded yet.</p>
        )}
      </details>
    </Dialog>
  );
}
