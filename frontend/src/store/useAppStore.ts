import { create } from "zustand";
import { saved } from "../utils/storage";
export type Sort = "recent" | "tokens";
export type Dialog =
  "settings" | "sources" | "providers" | "limits" | "update" | null;
interface AppStore {
  provider: string;
  selected: string | null;
  paused: boolean;
  sort: Sort;
  sortDirection: "asc" | "desc";
  day: string | null;
  historyDay: string;
  search: string;
  agentsIncluded: boolean;
  range: string;
  dialog: Dialog;
  page: "overview" | "stats";
  setProvider: (v: string) => void;
  setSelected: (v: string | null) => void;
  setPaused: (v: boolean) => void;
  setSort: (v: Sort) => void;
  setDay: (v: string | null) => void;
  setHistoryDay: (v: string) => void;
  setSearch: (v: string) => void;
  setAgentsIncluded: (v: boolean) => void;
  setRange: (v: string) => void;
  setDialog: (v: Dialog) => void;
  setPage: (v: "overview" | "stats") => void;
}
const defaults = saved.get("dashboardDefaults", {
  range: "today",
  agents: true,
});
export const useAppStore = create<AppStore>((set) => ({
  provider: "all",
  selected: null,
  paused: false,
  sort: "recent",
  sortDirection: "desc",
  day: null,
  historyDay: "",
  search: "",
  agentsIncluded: defaults.agents !== false,
  range: defaults.range || "today",
  dialog: null,
  page: location.hash === "#stats" ? "stats" : "overview",
  setProvider: (provider) => set({ provider, selected: null }),
  setSelected: (selected) => set({ selected }),
  setPaused: (paused) => set({ paused }),
  setSort: (sort) =>
    set((s) => ({
      sort,
      sortDirection:
        s.sort === sort && s.sortDirection === "desc" ? "asc" : "desc",
    })),
  setDay: (day) => set({ day, selected: null }),
  setHistoryDay: (historyDay) => set({ historyDay, selected: null, day: null }),
  setSearch: (search) => set({ search }),
  setAgentsIncluded: (agentsIncluded) => set({ agentsIncluded }),
  setRange: (range) => set({ range, day: null }),
  setDialog: (dialog) => set({ dialog }),
  setPage: (page) => set({ page }),
}));
