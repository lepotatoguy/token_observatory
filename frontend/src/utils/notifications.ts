import { saved } from "./storage";
export const alertsEnabled = () =>
  saved.get("alerts", false) &&
  typeof Notification !== "undefined" &&
  Notification.permission === "granted";
export async function toggleAlerts() {
  if (typeof Notification === "undefined") return false;
  if (alertsEnabled()) {
    saved.set("alerts", false);
    return false;
  }
  const permission = await Notification.requestPermission();
  saved.set("alerts", permission === "granted");
  return permission === "granted";
}
export function alertOnce(key: string, title: string, body: string) {
  if (!alertsEnabled()) return;
  const done = saved.get<string[]>("alerted", []);
  if (done.includes(key)) return;
  try {
    new Notification(title, { body, icon: "/logo.svg", tag: key });
    saved.set("alerted", [...done, key].slice(-200));
  } catch {
    /* Browser may revoke notification permission after the last check. */
  }
}
