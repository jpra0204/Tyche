import { useQuery } from "@tanstack/react-query";

import { useApi } from "../../api/context";

export function useStatus(riskProfile: string) {
  const api = useApi();
  return useQuery({
    queryKey: ["status", riskProfile],
    queryFn: () => api.getStatus(riskProfile),
  });
}
