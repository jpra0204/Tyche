import { useQuery } from "@tanstack/react-query";

import { useApi } from "../../api/context";

export function usePaper() {
  const api = useApi();
  return useQuery({ queryKey: ["paper"], queryFn: () => api.getPaper() });
}
