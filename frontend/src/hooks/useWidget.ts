import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
export const useWidget = () => {
  const client = useQueryClient(),
    query = useQuery({
      queryKey: ["widget"],
      queryFn: api.widget,
      refetchInterval: 5000,
      retry: 0,
    }),
    save = useMutation({
      mutationFn: api.setWidget,
      onSuccess: (status) => client.setQueryData(["widget"], status),
    });
  return { query, save };
};
