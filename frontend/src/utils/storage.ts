const memory = new Map<string, unknown>();
export const saved = {
  get<T>(key: string, fallback: T): T {
    try {
      const value = localStorage.getItem("to." + key);
      return value === null ? fallback : (JSON.parse(value) as T);
    } catch {
      return memory.has(key) ? (memory.get(key) as T) : fallback;
    }
  },
  set<T>(key: string, value: T) {
    memory.set(key, value);
    try {
      localStorage.setItem("to." + key, JSON.stringify(value));
    } catch {
      /* Retain preferences in memory when browser storage is unavailable. */
    }
  },
};
