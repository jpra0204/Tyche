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
