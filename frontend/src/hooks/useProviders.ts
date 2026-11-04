import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
export function useProviders() {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["providers"],
    queryFn: api.providers,
    staleTime: 30000,
  });
  const mutation = useMutation({
    mutationFn: api.saveProviders,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["providers"] });
      void client.invalidateQueries({ queryKey: ["usage"] });
    },
  });
  return { ...query, save: mutation };
}
