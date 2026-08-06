// frontend/services/eval_dataset.ts
// M37.1 — RAG evaluation dataset HTTP service
//
// Style B(独立函数 + `import api from "./auth"`),跟 services/stock.ts 一致。
// 所有 endpoint 走项目标准信封:
//   - 列表:PaginatedResponse<T> → service 层拆成 EvalDatasetListResult
//   - 单项:SingleResponse<T>    → 返回 res.data.data
//   - 删除:ResponseBase         → 返回 res.data(包含 code / message)

import api from "./auth";
import type {
  EvalDatasetCreate,
  EvalDatasetDetail,
  EvalDatasetItem,
  EvalDatasetItemBulkImportRequest,
  EvalDatasetItemBulkImportResponse,
  EvalDatasetItemCreate,
  EvalDatasetItemListParams,
  EvalDatasetItemListResult,
  EvalDatasetListItem,
  EvalDatasetListParams,
  EvalDatasetListResult,
  EvalDatasetUpdate,
} from "@/types/eval_dataset";

export type {
  EvalDatasetItemListParams,
  EvalDatasetItemListResult,
  EvalDatasetListParams,
  EvalDatasetListResult,
};

const BASE = "/eval/datasets";

// ---------- dataset CRUD ----------

/** GET /api/v1/eval/datasets/ —— 列出当前租户可见的 datasets(含 builtin / NULL tenant_id)。 */
export async function listDatasets(
  params: EvalDatasetListParams = {},
): Promise<EvalDatasetListResult> {
  const res = await api.get(`${BASE}/`, { params });
  return {
    items: (res.data.data ?? []) as EvalDatasetListItem[],
    total: res.data.total ?? 0,
    page: res.data.page ?? params.page ?? 1,
    page_size: res.data.page_size ?? params.page_size ?? 20,
  };
}

/** GET /api/v1/eval/datasets/{id} —— 详情。 */
export async function getDataset(id: number): Promise<EvalDatasetDetail> {
  const res = await api.get(`${BASE}/${id}`);
  return res.data.data as EvalDatasetDetail;
}

/** POST /api/v1/eval/datasets/ —— 创建(tenant_id 由后端从 current_user 推导)。 */
export async function createDataset(
  payload: EvalDatasetCreate,
): Promise<EvalDatasetDetail> {
  const res = await api.post(`${BASE}/`, payload);
  return res.data.data as EvalDatasetDetail;
}

/** PUT /api/v1/eval/datasets/{id} —— 部分更新(kb_id 不可改)。 */
export async function updateDataset(
  id: number,
  payload: EvalDatasetUpdate,
): Promise<EvalDatasetDetail> {
  const res = await api.put(`${BASE}/${id}`, payload);
  return res.data.data as EvalDatasetDetail;
}

/** DELETE /api/v1/eval/datasets/{id} —— 级联删除 items。 */
export async function deleteDataset(id: number): Promise<void> {
  await api.delete(`${BASE}/${id}`);
}

// ---------- item CRUD ----------

/** GET /api/v1/eval/datasets/{id}/items —— 详情页表格分页用。 */
export async function listItems(
  datasetId: number,
  params: EvalDatasetItemListParams = {},
): Promise<EvalDatasetItemListResult> {
  const res = await api.get(`${BASE}/${datasetId}/items`, { params });
  return {
    items: (res.data.data ?? []) as EvalDatasetItem[],
    total: res.data.total ?? 0,
    page: res.data.page ?? params.page ?? 1,
    page_size: res.data.page_size ?? params.page_size ?? 50,
  };
}

/** POST /api/v1/eval/datasets/{id}/items —— 加一条 item。 */
export async function addItem(
  datasetId: number,
  payload: EvalDatasetItemCreate,
): Promise<EvalDatasetItem> {
  const res = await api.post(`${BASE}/${datasetId}/items`, payload);
  return res.data.data as EvalDatasetItem;
}

/** POST /api/v1/eval/datasets/{id}/items/bulk-import
 *  整批 200 OK;部分成功靠 imported_count + partial_errors 判断。 */
export async function bulkImportItems(
  datasetId: number,
  payload: EvalDatasetItemBulkImportRequest,
): Promise<EvalDatasetItemBulkImportResponse> {
  const res = await api.post(
    `${BASE}/${datasetId}/items/bulk-import`,
    payload,
  );
  return res.data.data as EvalDatasetItemBulkImportResponse;
}

/** DELETE /api/v1/eval/datasets/{id}/items/{item_id} —— 删单条 item。 */
export async function deleteItem(
  datasetId: number,
  itemId: number,
): Promise<void> {
  await api.delete(`${BASE}/${datasetId}/items/${itemId}`);
}