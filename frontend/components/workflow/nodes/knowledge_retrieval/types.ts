import type { ErrorStrategy, RetryConfig } from "../../_base/error/types";

export interface KBRetrievalConfig {
  kb_id?: number;
  kb_name_cache?: string;
  query?: string;
  top_k?: number;
  score_threshold?: number;
  rerank_enabled?: boolean;
  hybrid_search?: boolean;
  error_strategy?: ErrorStrategy | null;
  default_value?: Record<string, unknown> | null;
  retry_config?: RetryConfig | null;
  timeout?: number | null;
}
