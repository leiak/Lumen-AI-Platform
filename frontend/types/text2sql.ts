// frontend/types/text2sql.ts
// M33 — Text2SQL 智能问数 (T26)
//
// Backend Pydantic schemas live in backend/app/schemas/text2sql.py.
// The frontend reads `res.data.data` (SingleResponse.data) and
// `res.data.items / total / page / page_size` (PaginatedResponse).
// See CLAUDE.md §3.

export type Text2SqlStatus =
  | "pending"
  | "generating"
  | "executing"
  | "explaining"
  | "success"
  | "rejected"
  | "failed";

/** Body for POST /api/v1/text2sql/ask */
export interface Text2SqlAskRequest {
  data_source_id: number;
  question: string;
  async_run?: boolean;
}

/** Returned by POST /api/v1/text2sql/ask (sync) and async (pending) */
export interface Text2SqlAskResponse {
  query_id: number;
  status: Text2SqlStatus;
  generated_sql?: string | null;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  explanation?: string | null;
  confidence?: number | null;
  attempts: number;
  error_type?: string | null;
  error_message?: string | null;
  duration_ms?: number | null;
}

/** Row in the history list — strips the heavy rows_json blob */
export interface Text2SqlHistoryItem {
  id: number;
  data_source_id: number;
  question: string;
  question_preview: string;
  status: Text2SqlStatus;
  row_count: number | null;
  attempts: number;
  duration_ms: number | null;
  error_type: string | null;
  created_at: string;
}

/** Full detail returned by GET /history/{id} */
export interface Text2SqlDetail extends Omit<Text2SqlAskResponse, "query_id"> {
  id: number;
  tenant_id: number;
  user_id: number;
  data_source_id: number;
  question: string;
  generate_call_id: string | null;
  explain_call_id: string | null;
  updated_at: string;
}

/** DataSource CRUD */
export interface Text2SqlDataSource {
  id: number;
  tenant_id: number;
  name: string;
  db_name: string;
  table_allowlist: string[] | null;
  field_allowlist: Record<string, string[]> | null;
  max_rows: number;
  timeout_ms: number;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Text2SqlDataSourceCreate {
  name: string;
  db_name?: string;
  table_allowlist?: string[] | null;
  field_allowlist?: Record<string, string[]> | null;
  max_rows?: number;
  timeout_ms?: number;
  description?: string | null;
  is_active?: boolean;
}

export interface Text2SqlDataSourceUpdate
  extends Partial<Text2SqlDataSourceCreate> {}

/** Returned by GET /api/v1/text2sql/schema */
export interface Text2SqlSchemaResponse {
  data_source_id: number;
  db_name: string;
  table_count: number;
  schema_text: string;
  tables: Array<{ name: string; comment: string }>;
}
