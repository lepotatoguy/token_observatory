import { saved } from "./storage";
export type Theme = "auto" | "light" | "dark";
export function applyTheme(theme: Theme) {
  saved.set("theme", theme);
  document.documentElement.dataset.theme =
    theme === "auto"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : theme;
  document.documentElement.style.colorScheme =
    document.documentElement.dataset.theme;
  window.dispatchEvent(new Event("theme-change"));
}
