import type { ErrorStrategy, RetryConfig } from "../../_base/error/types";

export type Aggregation = "collect" | "sum" | "average" | "join" | "first" | "last";

export interface VariableAggregatorConfig {
  source_node_id?: string;
  source_var?: string;
  aggregation?: Aggregation;
  join_separator?: string;
  error_strategy?: ErrorStrategy | null;
  default_value?: Record<string, unknown> | null;
  retry_config?: RetryConfig | null;
  timeout?: number | null;
}
