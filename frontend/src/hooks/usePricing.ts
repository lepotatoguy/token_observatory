import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
export const usePricing = () =>
  useQuery({
    queryKey: ["pricing"],
    queryFn: api.pricing,
    refetchInterval: 3600000,
    staleTime: 3600000,
  });
