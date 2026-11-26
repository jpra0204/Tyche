// The run started from the page: one at a time, read again every moment while it runs.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { useApi } from "../../api/context";
import type { RunRequest } from "../../api/types";

export const CURRENT_RUN = ["run", "current"] as const;

// How often the page asks for new output while a run is going. Polling, not a stream:
// one plain GET that carries the token like every other call (ADR-0046).
const POLL_MS = 700;

export function useCurrentRun() {
  const api = useApi();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: CURRENT_RUN,
    queryFn: () => api.getCurrentRun(),
    refetchInterval: (q) => (q.state.data?.state === "running" ? POLL_MS : false),
  });

  // When a run ends, what it wrote is new: read the records and the status again.
  const state = query.data?.state;
  const number = query.data?.number;
  useEffect(() => {
    if (state !== undefined && state !== "running") {
      void queryClient.invalidateQueries({ queryKey: ["backtests"] });
      void queryClient.invalidateQueries({ queryKey: ["status"] });
    }
  }, [state, number, queryClient]);

  return query;
}


export function useStartRun() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: RunRequest) => api.startRun(request),
    onSuccess: (run) => queryClient.setQueryData(CURRENT_RUN, run),
  });
}
