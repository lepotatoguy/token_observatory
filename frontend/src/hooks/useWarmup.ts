import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
export const useWarmup = () => {
  const client = useQueryClient(),
    query = useQuery({
      queryKey: ["warmup"],
      queryFn: api.warmup,
      refetchInterval: 30000,
      retry: 0,
    }),
    save = useMutation({
      mutationFn: api.setWarmup,
      onSuccess: (status) => client.setQueryData(["warmup"], status),
    });
  return { query, save };
};
