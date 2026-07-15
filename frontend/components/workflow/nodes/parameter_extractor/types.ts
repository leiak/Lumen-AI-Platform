import type { ErrorStrategy, RetryConfig } from "../../_base/error/types";

export interface ParameterDefFE {
  name: string;
  type: "string" | "number" | "boolean";
  description: string;
  required: boolean;
}

export interface ParameterExtractorConfig {
  model_config_id?: number;
  model_name_cache?: string;
  input_text?: string;
  parameters?: ParameterDefFE[];
  instruction?: string;
  temperature?: number;
  error_strategy?: ErrorStrategy | null;
  default_value?: Record<string, unknown> | null;
  retry_config?: RetryConfig | null;
  timeout?: number | null;
}
