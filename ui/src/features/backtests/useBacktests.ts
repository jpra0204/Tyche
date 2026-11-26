import { useQuery } from "@tanstack/react-query";

import { useApi } from "../../api/context";

export function useBacktests() {
  const api = useApi();
  return useQuery({ queryKey: ["backtests"], queryFn: () => api.listBacktests() });
}

export function useBacktestReport(runId: string) {
  const api = useApi();
  return useQuery({
    queryKey: ["backtests", runId, "report"],
    queryFn: () => api.getBacktestReport(runId),
  });
}
