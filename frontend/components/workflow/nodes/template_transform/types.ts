import type { ErrorStrategy, RetryConfig } from "../../_base/error/types";

export interface TemplateTransformConfig {
  template?: string;
  error_strategy?: ErrorStrategy | null;
  default_value?: Record<string, unknown> | null;
  retry_config?: RetryConfig | null;
  timeout?: number | null;
}
