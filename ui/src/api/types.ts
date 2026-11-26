// Names for the API's models, generated from its schema (see schema.d.ts).
// After changing tyche.api.models: `make ui-types`.
import type { components } from "./schema";

type Schemas = components["schemas"];

export type StatusView = Schemas["StatusView"];
export type ConfigView = Schemas["ConfigView"];
export type SecretsView = Schemas["SecretsView"];
export type TradingView = Schemas["TradingView"];
export type AccountView = Schemas["AccountView"];
export type HaltView = Schemas["HaltView"];
export type RunView = Schemas["RunView"];
export type RunLine = Schemas["RunLine"];
export type FetchRequest = Schemas["FetchRequest"];
export type BacktestRequest = Schemas["BacktestRequest"];
export type ReportRequest = Schemas["ReportRequest"];
export type RunRequest =
  | FetchRequest
  | BacktestRequest
  | ReportRequest
  | Schemas["PaperRunRequest"]
  | Schemas["KillRequest"]
  | Schemas["ResumeRequest"]
  | Schemas["WalkForwardRequest"]
  | Schemas["SweepRequest"]
  | Schemas["CapitalRunRequest"]
  | Schemas["CompareProfilesRequest"];
export type DataView = Schemas["DataView"];
export type BacktestSummary = Schemas["BacktestSummary"];
export type PaperRunRequest = Schemas["PaperRunRequest"];
export type KillRequest = Schemas["KillRequest"];
export type ResumeRequest = Schemas["ResumeRequest"];
export type PaperView = Schemas["PaperView"];
export type ReconciliationView = Schemas["ReconciliationView"];
export type AlertView = Schemas["AlertView"];
export type ResearchView = Schemas["ResearchView"];
export type StudySummary = Schemas["StudySummary"];
export type StudyKind = StudySummary["kind"];
