import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import { useUpdates } from "../../hooks/useUpdates";
import { Dialog } from "./Dialog";
const runningStates = [
  "starting",
  "downloading",
  "verifying",
  "installing",
  "restarting",
];
export function UpdateDialog() {
  const close = useAppStore((s) => s.setDialog),
    client = useQueryClient(),
    [target, setTarget] = useState<string | null>(null),
    [started, setStarted] = useState(0),
    [notify, setNotify] = useState(true),
    [message, setMessage] = useState(""),
    { data, error } = useUpdates(!!target),
    latest = data?.latest;
  useEffect(() => {
    if (data && !target) setNotify(data.notify);
  }, [data, target]);
  useEffect(() => {
    if (!target) return;
    const timer = window.setTimeout(() => {
      setMessage(
        "Token Observatory has not come back yet. Open it again, then reload this page.",
      );
      setTarget(null);
    }, 180000);
    return () => window.clearTimeout(timer);
  }, [target]);
  useEffect(() => {
    if (!target || !data) return;
    if (data.current === target) {
      location.reload();
      return;
    }
    if (Date.now() - started > 180000) {
      setMessage(
        "Token Observatory has not come back yet. Open it again, then reload this page.",
      );
      setTarget(null);
      return;
    }
    if (data.progress?.message) setMessage(data.progress.message);
    if (
      data.progress &&
      !runningStates.includes(data.progress.state) &&
      data.progress.state !== "idle"
    )
      setTarget(null);
  }, [data, target, started]);
  async function install() {
    if (!latest || target) return;
    setTarget(latest.version);
    setStarted(Date.now());
    setMessage("Starting update…");
    try {
      await api.saveUpdate({ notify });
      const status = await api.installUpdate();
      client.setQueryData(["updates"], status);
      if (status.progress?.message) setMessage(status.progress.message);
    } catch (e) {
      setTarget(null);
      setMessage(
        `Update failed: ${e instanceof Error ? e.message : String(e)}`,
      );
    }
  }
  async function dismiss() {
    try {
      await api.saveUpdate({
        notify,
        ...(latest ? { dismiss: latest.version } : {}),
      });
      await client.invalidateQueries({ queryKey: ["updates"] });
      close(null);
    } catch (e) {
      setMessage(
        `Could not save the setting: ${e instanceof Error ? e.message : String(e)}`,
      );
    }
  }
  return (
    <Dialog
      title={
        latest ? `Token Observatory ${latest.version} is available` : "Updates"
      }
      busy={!!target}
      onClose={() => {
        void dismiss();
      }}
    >
      <p>
        {latest
          ? `A new version is available (you have ${data?.current}). Update now downloads it from GitHub, verifies release checksums, installs it and restarts the dashboard.`
          : `Current version: ${data?.current || "Reading…"}`}
      </p>
      {latest && (
        <>
          <div className="update-notes">{latest.notes || ""}</div>
          <p>
            <a href={latest.url} target="_blank" rel="noreferrer">
              Full release notes on GitHub
            </a>
          </p>
        </>
      )}
      <label className="update-check">
        <input
          type="checkbox"
          checked={notify}
          onChange={(e) => setNotify(e.target.checked)}
          disabled={!!target}
        />{" "}
        Notify me about future updates
      </label>
      <p className="update-progress" role="status">
        {message ||
          (target && error ? "Restarting Token Observatory…" : error?.message)}
      </p>
      <div className="update-actions">
        <button
          className="button"
          disabled={!!target}
          onClick={() => {
            void dismiss();
          }}
        >
          Not now
        </button>
        {latest && (
          <button
            className="button primary"
            disabled={!!target || data?.progress?.state === "manual"}
            onClick={() => {
              void install();
            }}
          >
            {target ? "Updating…" : "Update now"}
          </button>
        )}
      </div>
    </Dialog>
  );
}
