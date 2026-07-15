import type { ErrorStrategy, RetryConfig } from "../../_base/error/types";

export interface CategoryFE {
  id: string;
  name: string;
  description: string;
}

export interface QuestionClassifierConfig {
  model_config_id?: number;
  model_name_cache?: string;
  input_text?: string;
  categories?: CategoryFE[];
  instruction?: string;
  temperature?: number;
  error_strategy?: ErrorStrategy | null;
  default_value?: Record<string, unknown> | null;
  retry_config?: RetryConfig | null;
  timeout?: number | null;
}
