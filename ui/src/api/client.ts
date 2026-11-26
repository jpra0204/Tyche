// The one place the console talks to Tyche's API. Every call carries the token.
import type { StatusView } from "./types";

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
}

export function createApi(token: string): Api {
  async function get<T>(path: string, query: Record<string, string> = {}): Promise<T> {
    const search = new URLSearchParams(query).toString();
    const response = await fetch(`/api${path}${search ? `?${search}` : ""}`, {
      headers: { [TOKEN_HEADER]: token, Accept: "application/json" },
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
      const detail = typeof body?.detail === "string" ? body.detail : response.statusText;
      throw new ApiError(response.status, detail);
    }
    return (await response.json()) as T;
  }

  return {
    getStatus: (riskProfile) => get<StatusView>("/status", { risk_profile: riskProfile }),
  };
}
