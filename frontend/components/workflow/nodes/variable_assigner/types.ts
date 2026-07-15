import type { ErrorStrategy, RetryConfig } from "../../_base/error/types";

export type ValueSource = "constant" | "upstream_ref" | "expression";

export interface AssignmentFE {
  variable: string;
  value_source: ValueSource;
  constant_value?: unknown;
  upstream_ref?: string[];
  expression?: string;
}

export interface VariableAssignerConfig {
  operations?: AssignmentFE[];
  error_strategy?: ErrorStrategy | null;
  default_value?: Record<string, unknown> | null;
  retry_config?: RetryConfig | null;
  timeout?: number | null;
}
