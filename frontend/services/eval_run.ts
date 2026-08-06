// frontend/services/eval_run.ts
// M37.2 — RAG evaluation run HTTP service
//
// Style B(独立函数 + import api from "./auth"),跟 services/eval_dataset.ts 一致。
// 5 endpoint 拆 5 个函数,Compare 跟其它独立(不是按 run 子端点)。

import api from "./auth";
import type {
  EvalRunCancel,
  EvalRunCompareRequest,
  EvalRunCompareResponse,
  EvalRunCreate,
  EvalRunDetail,
  EvalRunDetailWithResults,
  EvalRunListItem,
  EvalRunListParams,
  EvalRunListResult,
} from "@/types/eval_run";

export type { EvalRunListParams, EvalRunListResult };

const BASE = "/eval/runs";

// ---------- list ----------

/** GET /api/v1/eval/runs/ — 列出当前租户可见的 runs。 */
export async function listRuns(
  params: EvalRunListParams = {},
): Promise<EvalRunListResult> {
  const res = await api.get(`${BASE}/`, { params });
  return {
    items: (res.data.data ?? []) as EvalRunListItem[],
    total: res.data.total ?? 0,
    page: res.data.page ?? params.page ?? 1,
    page_size: res.data.page_size ?? params.page_size ?? 20,
  };
}

// ---------- start / detail / cancel ----------

/** POST /api/v1/eval/runs/ — 启动(eager Celery 模式下同步跑完)。 */
export async function startRun(payload: EvalRunCreate): Promise<EvalRunDetail> {
  const res = await api.post(`${BASE}/`, payload);
  return res.data.data as EvalRunDetail;
}

/** GET /api/v1/eval/runs/{id} — 详情。include_results=true 拿 results 列表。 */
export async function getRun(
  id: number,
  options: { includeResults?: boolean; resultsPage?: number; resultsPageSize?: number } = {},
): Promise<EvalRunDetailWithResults> {
  const params: Record<string, unknown> = {};
  if (options.includeResults) params.include_results = true;
  if (options.resultsPage) params.results_page = options.resultsPage;
  if (options.resultsPageSize) params.results_page_size = options.resultsPageSize;
  const res = await api.get(`${BASE}/${id}`, { params });
  return res.data.data as EvalRunDetailWithResults;
}

/** POST /api/v1/eval/runs/{id}/cancel — 取消 pending / running run。 */
export async function cancelRun(
  id: number,
  payload: EvalRunCancel = {},
): Promise<EvalRunDetail> {
  const res = await api.post(`${BASE}/${id}/cancel`, payload);
  return res.data.data as EvalRunDetail;
}

// ---------- compare ----------

/** POST /api/v1/eval/runs/compare — 同 dataset 两 run 对比。 */
export async function compareRuns(
  payload: EvalRunCompareRequest,
): Promise<EvalRunCompareResponse> {
  const res = await api.post(`${BASE}/compare`, payload);
  return res.data.data as EvalRunCompareResponse;
}
