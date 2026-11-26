import { useQuery } from "@tanstack/react-query";

import { useApi } from "../../api/context";

export function useConfig() {
  const api = useApi();
  return useQuery({ queryKey: ["config"], queryFn: () => api.getConfig() });
}
