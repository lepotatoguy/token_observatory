export const date = (at: number | null | undefined) =>
  at ? new Date(at * 1000).toLocaleString() : "Timestamp unavailable";
const pad = (n: number) => String(n).padStart(2, "0");
export const dayKey = (at: number) => {
  const d = new Date(at * 1000);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};
export const dayStart = (key: string) => {
  const [y, m, d] = key.split("-").map(Number);
  return new Date(y, m - 1, d).getTime() / 1000;
};
export const shiftDay = (key: string, days: number) => {
  const [y, m, d] = key.split("-").map(Number);
  return dayKey(new Date(y, m - 1, d + days).getTime() / 1000);
};
export const dayLabel = (key: string) =>
  new Date(dayStart(key) * 1000).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
export function relative(
  at: number | null | undefined,
  now = Date.now() / 1000,
) {
  if (!at) return "Undated";
  const seconds = Math.max(0, Math.floor(now - at));
  return seconds < 60
    ? "Just now"
    : seconds < 3600
      ? `${Math.floor(seconds / 60)}m ago`
      : seconds < 86400
        ? `${Math.floor(seconds / 3600)}h ago`
        : new Date(at * 1000).toLocaleDateString(undefined, {
            month: "short",
            day: "numeric",
          });
}
export function cutoff(range: string, day: string | null, now: number) {
  if (day) return dayStart(day);
  if (range === "all") return 0;
  if (range === "today") return dayStart(dayKey(now));
  return now - (range === "48h" ? 2 : Number(range.replace("d", ""))) * 86400;
}
export const countdown = (seconds: number) => {
  const hours = Math.floor(Math.max(0, seconds) / 3600),
    minutes = Math.floor((Math.max(0, seconds) % 3600) / 60);
  return hours >= 24
    ? `${Math.floor(hours / 24)}d ${hours % 24}h`
    : `${hours}h ${minutes}m`;
};
