import { useQuery } from "@tanstack/react-query";

import { useApi } from "../../api/context";

export function useData() {
  const api = useApi();
  return useQuery({ queryKey: ["data"], queryFn: () => api.getData() });
}
