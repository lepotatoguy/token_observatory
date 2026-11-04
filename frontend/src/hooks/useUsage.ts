import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAppStore } from "../store/useAppStore";
export function useUsage() {
  const { paused, historyDay } = useAppStore();
  return useQuery({
    queryKey: ["usage", historyDay],
    queryFn: () => (historyDay ? api.history(historyDay) : api.usage()),
    placeholderData: (previous) => previous,
    refetchInterval: paused || historyDay ? false : 2000,
    refetchOnWindowFocus: !paused && !historyDay,
    refetchOnReconnect: !paused && !historyDay,
  });
}
export function useRefresh() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.refresh,
    onSuccess: () => client.invalidateQueries({ queryKey: ["usage"] }),
  });
}
