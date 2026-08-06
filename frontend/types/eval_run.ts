// frontend/types/eval_run.ts
// M37.2 — RAG evaluation run lifecycle types
//
// 1:1 mirror of backend lumen_schemas/eval_run.py.

export type EvalRunStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type EvalRunJudgeMetric = "faithfulness" | "answer_relevancy";

/** EvalRunConfig — 嵌套在 EvalRunCreate.config 里,前端表单字段。 */
export interface EvalRunConfig {
  name?: string;
  search_weights: Record<string, number>;
  top_k: number;
  rerank: boolean;
  rerank_top_n?: number;
  embedding_model_config_id: number;
  judge_model_config_id: number;
  chunking_strategy?: string;
  judge_metrics?: EvalRunJudgeMetric[];
}

/** POST /api/v1/eval/runs/ body。dataset_id 必填,config 嵌套。 */
export interface EvalRunCreate {
  dataset_id: number;
  config: EvalRunConfig;
  trace_id?: string;
}

/** GET /api/v1/eval/runs/ 列表行 —— 轻量,不含 metrics/report_markdown。 */
export interface EvalRunListItem {
  id: number;
  dataset_id: number;
  status: EvalRunStatus;
  total_items: number;
  completed_items: number;
  completed_count: number | null;     // service 算的 success count
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
  created_by: number | null;
}

/** GET /api/v1/eval/runs/{id} 详情 —— ListItem + 嵌套 config + metrics + report。 */
export interface EvalRunDetail extends EvalRunListItem {
  config: EvalRunConfig;
  metrics_json: EvalRunMetrics | null;
  report_markdown: string | null;
  trace_id: string | null;
}

/** spec §4.2 metrics_json 格式 — retrieval / answer / by_category / by_difficulty */
export interface EvalRunMetrics {
  retrieval: {
    hit_at_5: number;
    hit_at_10: number;
    mrr: number;
    ndcg_at_10: number;
    recall_at_10: number;
    latency_ms_p50?: number;
    latency_ms_p95?: number;
  };
  answer: {
    keyword_hit_rate: number;
    faithfulness_avg: number;
    answer_relevancy_avg: number;
    llm_judge_total_calls: number;
  };
  by_category: Record<string, { hit_at_5: number; mrr: number; count: number }>;
  by_difficulty: Record<string, { hit_at_5: number; mrr: number; count: number }>;
  totals: {
    items_total: number;
    items_success: number;
    items_failed: number;
  };
}

/** GET /api/v1/eval/runs/{id}?include_results=true 时多带 results 列表。 */
export interface EvalRunResultItem {
  id: number;
  run_id: number;
  item_id: number;
  query: string;
  retrieved_doc_ids: number[];
  retrieval_scores: number[];
  retrieved_contexts: string[] | null;
  answer: string | null;
  retrieval_metrics: EvalRunMetrics["retrieval"];
  answer_metrics: EvalRunMetrics["answer"] | null;
  llm_judge_calls: unknown[] | null;
  latency_ms: number | null;
  error_message: string | null;
  created_at: string;
}

export interface EvalRunDetailWithResults extends EvalRunDetail {
  results: EvalRunResultItem[];
  results_total: number;
  results_page: number;
  results_page_size: number;
}

/** POST /api/v1/eval/runs/{id}/cancel body。 */
export interface EvalRunCancel {
  reason?: string;
}

/** POST /api/v1/eval/runs/compare body。 */
export interface EvalRunCompareRequest {
  run_id_a: number;
  run_id_b: number;
}

/** Compare 响应 — winner 字段只有 "a" / "b" / "tie" */
export interface EvalRunCompareWinner {
  metric: string;
  winner: "a" | "b" | "tie";
  delta: number;
  pct?: number | null;
}

export interface EvalRunCompareItemDelta {
  item_id: number;
  query: string;
  retrieval_delta: Record<string, number> | null;
  answer_delta: Record<string, number> | null;
}

export interface EvalRunCompareResponse {
  run_id_a: number;
  run_id_b: number;
  per_item_delta: EvalRunCompareItemDelta[];
  aggregate_delta: Record<string, number>;
  winners: EvalRunCompareWinner[];
}

/** List runs 入参。 */
export interface EvalRunListParams {
  dataset_id?: number;
  status?: EvalRunStatus;
  page?: number;
  page_size?: number;
}

/** listRuns() 返回的扁平 shape — service 解 PaginatedResponse 信封。 */
export interface EvalRunListResult {
  items: EvalRunListItem[];
  total: number;
  page: number;
  page_size: number;
}
