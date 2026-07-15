import type { ErrorStrategy, RetryConfig } from "../../_base/error/types";

export interface CodeNodeConfig {
  code?: string;
  inputs_mapping?: Record<string, string>;
  output_var?: string;
  error_strategy?: ErrorStrategy | null;
  default_value?: Record<string, unknown> | null;
  retry_config?: RetryConfig | null;
  timeout?: number | null;
}
