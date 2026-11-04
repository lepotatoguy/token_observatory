import React from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./style.css";
import { applyTheme, type Theme } from "./utils/theme";
import { saved } from "./utils/storage";
let theme: Theme = saved.get<Theme>("theme", "auto");
try {
  const raw = localStorage.getItem("to.theme");
  if (raw === "light" || raw === "dark" || raw === "auto") theme = raw;
} catch {
  /* Follow system when browser storage is blocked. */
}
applyTheme(theme);
window
  .matchMedia("(prefers-color-scheme: dark)")
  .addEventListener("change", () => {
    if (saved.get<Theme>("theme", "auto") === "auto") applyTheme("auto");
  });
const client = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } },
});
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
