import { useState } from "react";
import { useWarmup } from "../../hooks/useWarmup";
import type { WarmupProvider, WarmupProviderName } from "../../types/warmup";
const names: Record<WarmupProviderName, string> = {
  claude: "Claude",
  codex: "Codex",
  minimax: "MiniMax",
};
const order: WarmupProviderName[] = ["claude", "codex", "minimax"];
const DEFAULT_TIME = "07:00";
const outcome = (row: WarmupProvider) => {
  const last = row.last[0];
  if (!last) return "No sends yet";
  const label = last.status === "skipped_active" ? "skipped, window already running" : last.status;
  return `Last: ${label} ${last.slot}${last.reason ? ` (${last.reason})` : ""}`;
};
export function WarmupSection() {
  const { query, save } = useWarmup(),
    [drafts, setDrafts] = useState<Partial<Record<WarmupProviderName, string>>>({}),
    [notice, setNotice] = useState(""),
    data = query.data,
    problem =
      notice ||
      save.error?.message ||
      (query.error ? "The warm-up settings could not be loaded." : "");
  function change(name: WarmupProviderName, row: WarmupProvider, next: Partial<WarmupProvider>) {
    setNotice("");
    save.mutate({
      provider: name,
      enabled: next.enabled ?? row.enabled,
      times: next.times ?? row.times,
      model: row.model,
    });
  }
  return (
    <section className="settings-section">
      <h3>Window warm-up</h3>
      <p className="insight-note">
        Sends "{data?.message ?? "hello"}" to the cheapest model at the local
        times you choose, so your five-hour window starts when you want it to.
        It uses a small amount of your quota and is meant for paid plans. It
        runs only while Token Observatory is running and skips a send when a
        window is already active.
      </p>
      {data &&
        order.map((name) => {
          const row = data.providers[name],
            draft = drafts[name] ?? DEFAULT_TIME;
          return (
            <fieldset key={name} className="warmup-card">
              <legend>{names[name]}</legend>
              <label className="update-check">
                <input
                  type="checkbox"
                  checked={row.enabled}
                  disabled={!!row.unavailable || save.isPending}
                  onChange={(e) => {
                    if (e.target.checked && row.times.length === 0) {
                      setNotice(`Add a time first for ${names[name]}.`);
                      return;
                    }
                    change(name, row, { enabled: e.target.checked });
                  }}
                />{" "}
                {names[name]} warm-up
              </label>
              {row.unavailable && <p className="insight-note">{row.unavailable}</p>}
              {row.times.length === 0 ? (
                <p className="insight-note">No times yet. Add the time of day to send it.</p>
              ) : (
                <ul className="warmup-times" aria-label={`${names[name]} send times`}>
                  {row.times.map((time) => (
                    <li key={time}>
                      <span>{time}</span>
                      <button
                        className="warmup-remove"
                        aria-label={`Remove ${names[name]} time ${time}`}
                        disabled={save.isPending}
                        onClick={() =>
                          change(name, row, {
                            times: row.times.filter((t) => t !== time),
                            enabled: row.enabled && row.times.length > 1,
                          })
                        }
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <div className="warmup-add">
                <label>
                  <span>New time (your local time)</span>
                  <input
                    type="time"
                    aria-label={`${names[name]} new time`}
                    value={draft}
                    onChange={(e) => setDrafts({ ...drafts, [name]: e.target.value })}
                  />
                </label>
                <button
                  className="button"
                  aria-label={`Add ${names[name]} time`}
                  disabled={save.isPending}
                  onClick={() => {
                    if (!draft) return setNotice("Choose a time first.");
                    if (row.times.includes(draft))
                      return setNotice(`${draft} is already in the list.`);
                    setDrafts({ ...drafts, [name]: DEFAULT_TIME });
                    change(name, row, { times: [...row.times, draft].sort() });
                  }}
                >
                  Add time
                </button>
              </div>
              {row.deferred && (
                <p className="insight-note">
                  The {row.deferred.slot} message is waiting for your limit to
                  reset. It sends at {row.deferred.send_at}.
                </p>
              )}
              {row.enabled && row.next && (
                <p className="insight-note">Next: {row.next}</p>
              )}
              <p className="insight-note">{outcome(row)}</p>
            </fieldset>
          );
        })}
      <p className="update-progress" role="status" aria-live="polite">
        {problem}
      </p>
    </section>
  );
}
