import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useMemo } from "react";
import { BrowserRouter, Route, Routes } from "react-router";

import { createApi } from "../api/client";
import { ApiContext } from "../api/context";
import { MissingToken } from "../components/MissingToken";
import { BacktestsPage } from "../features/backtests/BacktestsPage";
import { ReportPage } from "../features/backtests/ReportPage";
import { DataPage } from "../features/data/DataPage";
import { StatusPage } from "../features/status/StatusPage";
import { Layout } from "./Layout";
import { theme } from "./theme";

const queries = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: true } },
});

export function App({ token }: { token: string | null }) {
  const api = useMemo(() => (token ? createApi(token) : null), [token]);

  return (
    <MantineProvider theme={theme} defaultColorScheme="auto">
      {api === null ? (
        <MissingToken />
      ) : (
        <ApiContext.Provider value={api}>
          <QueryClientProvider client={queries}>
            <BrowserRouter>
              <Routes>
                <Route element={<Layout />}>
                  <Route index element={<StatusPage />} />
                  <Route path="data" element={<DataPage />} />
                  <Route path="backtests" element={<BacktestsPage />} />
                  <Route path="backtests/:runId" element={<ReportPage />} />
                  <Route path="*" element={<StatusPage />} />
                </Route>
              </Routes>
            </BrowserRouter>
          </QueryClientProvider>
        </ApiContext.Provider>
      )}
    </MantineProvider>
  );
}
