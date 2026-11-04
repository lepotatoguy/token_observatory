import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
export const useUpdates = (running = false) =>
  useQuery({
    queryKey: ["updates"],
    queryFn: api.update,
    refetchInterval: running ? 1000 : 3600000,
    retry: running ? 2 : 0,
  });
