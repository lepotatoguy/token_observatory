import { useEffect } from "react";
import type { Snapshot } from "../../types/snapshot";
import { useAppStore } from "../../store/useAppStore";
import { contextPercent, groupConversations } from "../../utils/conversations";
import { compact } from "../../utils/tokens";
import { alertOnce } from "../../utils/notifications";
export function PressureBanner({
  snapshot,
  now,
}: {
  snapshot: Snapshot;
  now: number;
}) {
  const {
      historyDay,
      setSelected,
      setProvider,
      setRange,
      setSearch,
      setDay,
      setPage,
    } = useAppStore(),
    hot = historyDay
      ? []
      : groupConversations(snapshot.sessions)
          .filter(
            (s) =>
              s.last && now - s.last < 3600 && (contextPercent(s) || 0) >= 80,
          )
          .sort((a, b) => (contextPercent(b) || 0) - (contextPercent(a) || 0));
  useEffect(() => {
    for (const s of hot)
      for (const level of [80, 95])
        if ((contextPercent(s) || 0) >= level)
          alertOnce(
            `context:${s.id}:${level}`,
            `Context ${level}% full`,
            `${s.title} is using ${contextPercent(s)?.toFixed(0)}% of its ${compact(s.capacity || 0)}-token window.`,
          );
  }, [hot]);
  if (!hot.length) return null;
  return (
    <div className="warning pressure" role="status">
      Context filling up:{" "}
      {hot.map((s) => (
        <button
          key={s.id}
          className="link"
          onClick={() => {
            setProvider("all");
            setRange("all");
            setSearch("");
            setDay(null);
            setPage("overview");
            setSelected(s.id);
          }}
        >
          {s.title} ({contextPercent(s)?.toFixed(0)}%)
        </button>
      ))}
    </div>
  );
}
