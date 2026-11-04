import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
export function useLimitControls() {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["limits"],
    queryFn: api.limits,
    staleTime: 2000,
  });
  const mutation = useMutation({
    mutationFn: api.saveLimits,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["limits"] });
      void client.invalidateQueries({ queryKey: ["usage"] });
    },
  });
  return { ...query, save: mutation };
}
