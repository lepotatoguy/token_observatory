import { useWidget } from "../../hooks/useWidget";
import type { WidgetStatus } from "../../types/widget";
function describe(status?: WidgetStatus) {
  if (!status) return "";
  if (!status.available) return status.reason ?? "The widget runtime is missing.";
  if (status.error) return status.error;
  if (!status.enabled) return "Off";
  if (status.running) return "Running";
  return status.starting ? "Starting" : "Waiting for the widget to start";
}
export function WidgetSection() {
  const { query, save } = useWidget(),
    status = query.data,
    problem = save.error?.message || (query.error ? "The widget status could not be loaded." : "");
  return (
    <section className="settings-section">
      <h3>Floating widget</h3>
      <label className="update-check">
        <input
          type="checkbox"
          checked={status?.enabled ?? false}
          disabled={!status || !status.available || save.isPending}
          onChange={(e) => save.mutate(e.target.checked)}
        />{" "}
        Floating widget
      </label>
      <p className="insight-note">
        A small always-on-top pill with your session and weekly quota. Drag it
        anywhere; right-click it for options.
      </p>
      <p className="update-progress" role="status" aria-live="polite">
        {problem || describe(status)}
      </p>
    </section>
  );
}
