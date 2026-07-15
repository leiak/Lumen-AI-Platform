import type { ErrorStrategy, RetryConfig } from "../../_base/error/types";

export interface ToolNodeConfig {
  tool_id?: number;
  tool_name_cache?: string;
  arguments?: Record<string, unknown>;
  error_strategy?: ErrorStrategy | null;
  default_value?: Record<string, unknown> | null;
  retry_config?: RetryConfig | null;
  timeout?: number | null;
}
