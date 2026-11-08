import { useAppStore } from "../../store/useAppStore";
import { useCheckUpdate, useUpdates } from "../../hooks/useUpdates";
export function UpdateSection() {
  const setDialog = useAppStore((s) => s.setDialog),
    known = useUpdates().data,
    check = useCheckUpdate(),
    result = check.data,
    latest = result?.latest,
    failed = !!check.error || !!result?.error;
  return (
    <section className="settings-section">
      <h3>Updates</h3>
      <button
        className="button"
        disabled={check.isPending}
        onClick={() => check.mutate()}
      >
        {check.isPending ? "Checking" : "Check for updates"}
      </button>
      <p className="insight-note">
        Token Observatory also checks once a day. You have{" "}
        {result?.current ?? known?.current ?? "an unknown version"}.
      </p>
      <p className="update-progress" role="status" aria-live="polite">
        {result?.checks === false && "Update checks are disabled on this computer."}
        {failed && "Update check failed. Try again later."}
        {result && result.checks !== false && !failed && !latest && (
          <>You are on the latest version ({result.current}).</>
        )}
        {latest && result?.checks !== false && (
          <>
            {" "}Version {latest.version} is available.{" "}
            <button className="button" onClick={() => setDialog("update")}>
              View update
            </button>
          </>
        )}
      </p>
    </section>
  );
}
