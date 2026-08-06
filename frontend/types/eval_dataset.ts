// frontend/types/eval_dataset.ts
// M37.1 — RAG evaluation dataset CRUD
//
// 1:1 mirror of backend lumen_schemas/eval_dataset.py.
// tenant_id=null 表示 builtin dataset(全局可见,所有租户都能读)。

// ---------- enum literal types ----------

export type EvalDatasetSource = "manual" | "imported" | "synthetic";

export type EvalDatasetCategory =
  | "factual"
  | "reasoning"
  | "multi_hop"
  | "keyword_heavy"
  | "out_of_scope";

export type EvalDatasetDifficulty = "easy" | "medium" | "hard";

// ---------- dataset (parent) shapes ----------

/** GET /api/v1/eval/datasets/ 列表行 —— 轻量,不含 description。 */
export interface EvalDatasetListItem {
  id: number;
  kb_id: number;
  tenant_id: number | null;        // null = builtin
  name: string;
  source: EvalDatasetSource;
  is_active: number;               // 1 / 0
  item_count: number | null;       // 由 service COUNT(*) 填充
  created_at: string;
  updated_at: string;
}

/** GET /api/v1/eval/datasets/{id} 详情 —— ListItem + description + created_by。 */
export interface EvalDatasetDetail extends EvalDatasetListItem {
  description: string | null;
  created_by: number | null;
}

/** POST /api/v1/eval/datasets/ body。tenant_id 由后端从 current_user 推导。 */
export interface EvalDatasetCreate {
  kb_id: number;
  name: string;
  description?: string;
  source?: EvalDatasetSource;      // default "manual"
}

/** PUT /api/v1/eval/datasets/{id} body —— 所有字段 Optional,不允许改 kb_id。 */
export interface EvalDatasetUpdate {
  name?: string;
  description?: string;
  source?: EvalDatasetSource;
  is_active?: number;
}

// ---------- item (child) shapes ----------

export interface EvalDatasetItem {
  id: number;
  dataset_id: number;
  query: string;
  expected_doc_ids: number[];
  expected_answer: string | null;
  answer_keywords: string[] | null;
  category: EvalDatasetCategory | null;
  difficulty: EvalDatasetDifficulty | null;
  notes: string | null;
  created_at: string;
}

/** POST /api/v1/eval/datasets/{id}/items body。 */
export interface EvalDatasetItemCreate {
  query: string;
  expected_doc_ids?: number[];
  expected_answer?: string;
  answer_keywords?: string[];
  category?: EvalDatasetCategory;
  difficulty?: EvalDatasetDifficulty;
  notes?: string;
}

/** PATCH /api/v1/eval/datasets/{id}/items/{item_id} body(M37.1 follow-up)。
 *  全字段 Optional —— PATCH 语义,只传要改的字段。
 *  ``query`` 在 Create 是必填,在 Update 允许空(表示不改)。 */
export interface EvalDatasetItemUpdate {
  query?: string;
  expected_doc_ids?: number[];
  expected_answer?: string | null;
  answer_keywords?: string[] | null;
  category?: EvalDatasetCategory;
  difficulty?: EvalDatasetDifficulty;
  notes?: string | null;
}

// ---------- bulk import ----------

/** 单行 bulk import row —— category/difficulty Literal 严格校验
 *  (服务端 per-row Pydantic 校验,失败行进 partial_errors)。
 *
 * 后端 List[Dict[str, Any]] 接受任意形状,但前端按这个 interface 组装。 */
export interface EvalDatasetItemBulkImportRow {
  query: string;
  expected_doc_ids?: number[];
  expected_answer?: string;
  answer_keywords?: string[];
  category?: EvalDatasetCategory;
  difficulty?: EvalDatasetDifficulty;
  notes?: string;
}

/** POST /api/v1/eval/datasets/{id}/items/bulk-import body。 */
export interface EvalDatasetItemBulkImportRequest {
  rows: EvalDatasetItemBulkImportRow[];
}

/** 单行失败详情 —— 前端表格用 row_index 高亮错误行。 */
export interface EvalDatasetItemBulkImportError {
  row_index: number;              // 0-based,与原始 rows 列表下标一致
  error: string;                  // Pydantic 校验失败 / DB 错误一行摘要
}

/** POST bulk-import response —— 整批 200 OK,部分成功靠 imported_count + partial_errors 判断。 */
export interface EvalDatasetItemBulkImportResponse {
  imported_count: number;
  failed_count: number;
  partial_errors: EvalDatasetItemBulkImportError[];
}

// ---------- list query params ----------

export interface EvalDatasetListParams {
  kb_id?: number;
  page?: number;
  page_size?: number;
}

/** listDatasets() 返回的扁平 shape —— service 解 PaginatedResponse 信封。 */
export interface EvalDatasetListResult {
  items: EvalDatasetListItem[];
  total: number;
  page: number;
  page_size: number;
}

// ---------- items list ----------

export interface EvalDatasetItemListParams {
  page?: number;
  page_size?: number;
}

export interface EvalDatasetItemListResult {
  items: EvalDatasetItem[];
  total: number;
  page: number;
  page_size: number;
}