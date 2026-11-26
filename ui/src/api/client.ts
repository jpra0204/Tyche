// The one place the console talks to Tyche's API. Every call carries the token.
import type {
  BacktestSummary,
  DataView,
  PaperView,
  RunRequest,
  RunView,
  StatusView,
} from "./types";

export const TOKEN_HEADER = "X-Tyche-Token";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export interface Api {
  getStatus(riskProfile: string): Promise<StatusView>;
  getData(): Promise<DataView>;
  getPaper(): Promise<PaperView>;
  listBacktests(): Promise<BacktestSummary[]>;
  getBacktestReport(runId: string): Promise<string>;
  startRun(request: RunRequest): Promise<RunView>;
  getCurrentRun(): Promise<RunView | null>;
}

// FastAPI answers a refused request with `detail`: a sentence, or for a form that does
// not validate, a list of {loc, msg}.
function describe(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item: { loc?: unknown[]; msg?: string }) => {
      const field = Array.isArray(item.loc) ? item.loc.slice(2).join(".") : "";
      return field ? `${field}: ${item.msg ?? "invalid"}` : (item.msg ?? "invalid");
    });
    if (messages.length > 0) return messages.join("; ");
  }
  return fallback;
}

export function createApi(token: string): Api {
  async function call(path: string, init: RequestInit = {}, accept = "application/json") {
    const response = await fetch(`/api${path}`, {
      ...init,
      headers: { [TOKEN_HEADER]: token, Accept: accept, ...init.headers },
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
      throw new ApiError(response.status, describe(body?.detail, response.statusText));
    }
    return response;
  }

  async function get<T>(path: string, query: Record<string, string> = {}): Promise<T> {
    const search = new URLSearchParams(query).toString();
    const response = await call(`${path}${search ? `?${search}` : ""}`);
    return (await response.json()) as T;
  }

  return {
    getStatus: (riskProfile) => get<StatusView>("/status", { risk_profile: riskProfile }),
    getData: () => get<DataView>("/data"),
    getPaper: () => get<PaperView>("/paper"),
    listBacktests: () => get<BacktestSummary[]>("/backtests"),
    getBacktestReport: async (runId) => {
      const response = await call(`/backtests/${encodeURIComponent(runId)}/report`, {}, "text/html");
      return await response.text();
    },
    startRun: async (request) => {
      const response = await call("/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });
      return (await response.json()) as RunView;
    },
    getCurrentRun: () => get<RunView | null>("/runs/current"),
  };
}
