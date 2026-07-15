// frontend/types/customer.ts
// M33 — 客户管理 (CRM)
//
// TypeScript mirror of backend Pydantic schemas (see
// backend/app/schemas/customer.py + spec
// docs/superpowers/specs/2026-06-20-customer-management-design.md §4.3).
//
// Conventions (matches types/wx-publisher.ts):
// - Timestamps are ISO 8601 strings.
// - Optional fields use `null` rather than `undefined`.
// - Enum fields use Literal unions.
// - ``PaginatedResponse<T>`` unwrapped into flat list shape by the
//   service layer (services/customer.ts).

// === Enum Literals =========================================================

export type CustomerLevel = "vip" | "normal" | "potential" | "lost";
export type CustomerSource =
  | "referral"
  | "website"
  | "exhibition"
  | "ad"
  | "other";
export type CustomerGender = "M" | "F" | "U";
export type CustomerCompanySize =
  | "1-10"
  | "11-50"
  | "51-200"
  | "201-1000"
  | "1000+";
export type FollowUpType =
  | "phone"
  | "wechat"
  | "email"
  | "meeting"
  | "other";
export type FieldType =
  | "text"
  | "number"
  | "date"
  | "select"
  | "multiselect"
  | "textarea";

// === Customer main entity ==================================================

export interface CustomerCreate {
  name: string;
  owner_user_id: number;
  phone?: string | null;
  email?: string | null;
  wechat?: string | null;
  gender?: CustomerGender | null;
  birthday?: string | null;
  address?: string | null;
  avatar_url?: string | null;
  company_name?: string | null;
  company_position?: string | null;
  industry?: string | null;
  company_size?: CustomerCompanySize | null;
  company_website?: string | null;
  level?: CustomerLevel;
  source?: CustomerSource | null;
  tags?: string[] | null;
  custom_fields?: Record<string, unknown> | null;
  remark?: string | null;
}

export interface CustomerUpdate {
  name?: string;
  owner_user_id?: number;
  phone?: string | null;
  email?: string | null;
  wechat?: string | null;
  gender?: CustomerGender | null;
  birthday?: string | null;
  address?: string | null;
  avatar_url?: string | null;
  company_name?: string | null;
  company_position?: string | null;
  industry?: string | null;
  company_size?: CustomerCompanySize | null;
  company_website?: string | null;
  level?: CustomerLevel;
  source?: CustomerSource | null;
  tags?: string[] | null;
  custom_fields?: Record<string, unknown> | null;
  remark?: string | null;
}

export interface CustomerListItem {
  id: number;
  name: string;
  /** 列表里手机号脱敏(中间 4 位 ``*``),如 ``"138****8000"``。详情里走 ``phone``。 */
  phone_masked?: string | null;
  email?: string | null;
  company_name?: string | null;
  company_position?: string | null;
  level: string;
  source?: string | null;
  tags?: string[] | null;
  owner_user_id: number;
  owner_user_name?: string | null;
  last_follow_up_at?: string | null;
  next_follow_up_at?: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CustomFieldResolved {
  key: string;
  label: string;
  type: FieldType | string;
  value?: unknown;
  required: boolean;
  options?: string[] | null;
}

export interface CustomerDetail {
  id: number;
  name: string;
  /** 详情里手机号完整。 */
  phone?: string | null;
  email?: string | null;
  wechat?: string | null;
  avatar_url?: string | null;
  gender?: string | null;
  birthday?: string | null;
  address?: string | null;

  company_name?: string | null;
  company_position?: string | null;
  industry?: string | null;
  company_size?: string | null;
  company_website?: string | null;

  level: string;
  source?: string | null;
  tags?: string[] | null;
  custom_fields?: Record<string, unknown> | null;
  custom_fields_schema_resolved: CustomFieldResolved[];
  remark?: string | null;

  owner_user_id: number;
  owner_user_name?: string | null;
  created_by: number;
  last_follow_up_at?: string | null;
  next_follow_up_at?: string | null;
  follow_ups_count: number;

  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// === FollowUp ==============================================================

export interface FollowUpCreate {
  follow_up_type: FollowUpType;
  content: string;
  next_step?: string | null;
  next_follow_up_at?: string | null;
}

export interface FollowUpUpdate {
  follow_up_type?: FollowUpType;
  content?: string;
  next_step?: string | null;
  next_follow_up_at?: string | null;
}

export interface FollowUpResponse {
  id: number;
  customer_id: number;
  follow_up_type: string;
  content: string;
  next_step?: string | null;
  next_follow_up_at?: string | null;
  ai_suggested: boolean;
  user_id: number;
  user_name?: string | null;
  created_at: string;
}

export interface UpcomingFollowUpItem {
  customer_id: number;
  customer_name: string;
  level: string;
  owner_user_id: number;
  next_follow_up_at: string;
  last_follow_up_content?: string | null;
  /** 距今天数(负数 = 过期)。 */
  days_until_due: number;
}

// === AI Advisor ============================================================

export interface AIAdvisorRequest {
  model_config_id?: number | null;
  focus?: string | null;
}

export interface AIAdvisorResponse {
  suggested_message: string;
  suggested_next_follow_up_at?: string | null;
  reasoning: string;
  llm_call_id: string;
  duration_ms: number;
}

// === CustomerFieldDefinition ===============================================

export interface CustomerFieldDefinitionCreate {
  /** 英文 + 下划线,小写开头(正则 ``^[a-z][a-z0-9_]{0,49}$``)。 */
  field_key: string;
  field_label: string;
  field_type: FieldType;
  /** select / multiselect 时必填。 */
  options?: string[] | null;
  required?: boolean;
  order_index?: number;
}

export interface CustomerFieldDefinitionUpdate {
  /** field_key 创建后不可修改。 */
  field_label?: string;
  field_type?: FieldType;
  options?: string[] | null;
  required?: boolean;
  order_index?: number;
  is_active?: boolean;
}

export interface CustomerFieldDefinitionResponse {
  id: number;
  field_key: string;
  field_label: string;
  field_type: string;
  options?: string[] | null;
  required: boolean;
  order_index: number;
  is_active: boolean;
  created_by: number;
  created_at: string;
  updated_at: string;
}

// === List params ============================================================

export interface CustomerListParams {
  page?: number;
  page_size?: number;
  keyword?: string;
  /** 多选 level(逗号分隔传给后端)。 */
  levels?: CustomerLevel[];
  sources?: CustomerSource[];
  owner_user_id?: number;
  industry?: string;
  /** 多 tag AND 过滤。 */
  tags?: string[];
  next_follow_up_before?: string;
  is_active?: boolean;
  sort?: string;
}

export interface UpcomingFollowUpsParams {
  page?: number;
  page_size?: number;
  owner_user_id?: number;
  days?: number;
}

export interface CustomerListResult<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}