// frontend/types/wx-publisher.ts
// M32 — 公众号助手 (WeChat Publisher)
//
// TypeScript mirror of backend Pydantic schemas (see
// backend/app/schemas/wx_publisher/__init__.py + spec
// docs/superpowers/specs/2026-06-17-wx-publisher-design.md §4).
//
// Conventions:
// - Timestamps are ISO 8601 strings (matches Pydantic default JSON encoding).
// - Optional fields use `null` rather than `undefined` to align with
//   `SingleResponse<T>` envelope shape.
// - Enum fields use `as const` Literal unions so the UI gets exhaustiveness
//   checking in switch statements.
//
// We use the project-wide `PaginatedResponse<T>` from types/api.ts for list
// endpoints; service layer (services/wx-publisher.ts) unwraps it into a
// flat `{ items, total, page, page_size }` shape so callers can stay
// ergonomic without re-reading res.data.total every time.

// === Enum Literals =========================================================

export type WxAccountType = "subscription" | "service" | "enterprise";

export type WxTemplateCategory =
  | "minimal"
  | "tech"
  | "magazine"
  | "literary"
  | "business";

export type WxDraftStatus =
  | "draft"
  | "rendering"
  | "ready"
  | "publishing"
  | "published"
  | "failed";

export type WxMaterialSourceType = "kb" | "manual" | "url";

export type WxPublishRecordStatus =
  | "queued"
  | "uploading"
  | "uploaded"
  | "mass_sending"
  | "success"
  | "failed";

export type WxAIStyle = "总-分-总" | "观点递进" | "故事+感悟" | "FAQ 形式";

// === Account ================================================================

export interface WxAccountCreate {
  name: string;
  app_id: string;
  app_secret: string;
  account_type?: WxAccountType;
  is_mock?: boolean;
  ip_whitelist?: string[] | null;
}

export interface WxAccountUpdate {
  name?: string;
  is_active?: boolean;
  ip_whitelist?: string[] | null;
  is_mock?: boolean;
}

export interface WxAccountResponse {
  id: number;
  name: string;
  app_id: string;
  app_secret_masked: string;
  account_type: string;
  is_mock: boolean;
  is_active: boolean;
  last_verified_at?: string | null;
  created_at: string;
}

export interface WxAccountDetail extends WxAccountResponse {
  access_token_expires_at?: string | null;
  ip_whitelist?: string[] | null;
}

export interface WxAccountVerifyResponse {
  account_id: number;
  valid: boolean;
  message: string;
  verified_at: string;
}

/** Admin hard-delete summary. Returned by `POST /accounts/{id}/purge`. */
export interface WxAccountPurgeResponse {
  account_id: number;
  deleted_publish_records: number;
  drafts_set_null: number;
  deleted_account: boolean;
}

// === Template ===============================================================

export interface WxTemplateCreate {
  name: string;
  category: WxTemplateCategory;
  description?: string | null;
  html_body: string;
  css_variables: Record<string, unknown>;
  preview_html?: string | null;
  is_system?: boolean;
}

export interface WxTemplateUpdate {
  name?: string;
  category?: WxTemplateCategory;
  description?: string | null;
  html_body?: string;
  css_variables?: Record<string, unknown>;
  preview_html?: string | null;
}

export interface WxTemplateListItem {
  id: number;
  name: string;
  category: string;
  description?: string | null;
  is_system: boolean;
  usage_count: number;
  has_thumbnail: boolean;
  created_at: string;
}

export interface WxTemplateDetail extends WxTemplateListItem {
  html_body: string;
  css_variables: Record<string, unknown>;
  preview_html?: string | null;
  thumbnail_size?: number | null;
  created_by: number;
  updated_at: string;
}

// Response shape for create / update — same as list item.
export type WxTemplateResponse = WxTemplateListItem;

// === Draft ==================================================================

export interface WxDraftCreate {
  title: string;
  content_markdown?: string;
  account_id?: number | null;
  template_id?: number | null;
  kb_id?: number | null;
  tags?: string[] | null;
}

export interface WxDraftUpdate {
  title: string;
  content_markdown?: string;
  account_id?: number | null;
  template_id?: number | null;
  kb_id?: number | null;
  tags?: string[] | null;
  summary?: string | null;
  author?: string | null;
}

export interface WxDraftListItem {
  id: number;
  title: string;
  account_id?: number | null;
  template_id?: number | null;
  status: WxDraftStatus | string;
  scheduled_at?: string | null;
  updated_at: string;
}

export interface WxDraftResponse extends WxDraftListItem {
  cover_image_id?: number | null;
  kb_id?: number | null;
  tags?: string[] | null;
  published_at?: string | null;
  wechat_media_id?: string | null;
  error_message?: string | null;
}

export interface WxDraftDetail extends WxDraftResponse {
  user_id: number;
  summary?: string | null;
  author?: string | null;
  content_markdown: string;
  content_html?: string | null;
  cover_url?: string | null;
  created_at: string;
  sections: WxDraftSectionResponse[];
}

// === Section ================================================================

export interface WxDraftSectionCreate {
  order_index: number;
  heading?: string | null;
  content_markdown?: string;
}

export interface WxDraftSectionUpdate {
  order_index: number;
  heading?: string | null;
  content_markdown?: string;
}

export interface WxDraftSectionResponse {
  id: number;
  order_index: number;
  heading?: string | null;
  content_markdown: string;
  content_html?: string | null;
  ai_prompt?: string | null;
  ai_model_config_id?: number | null;
}

export interface WxDraftSectionReorderRequest {
  orders: Array<[number, number]>;
}

// === M32.1 — Paste HTML ====================================================

export interface WxDraftPasteHtmlRequest {
  /** HTML 字符串(飞书/网页 clipboard text/html). 后端转 MD 后 append 到 content_markdown */
  html: string;
}

// === Material ===============================================================

export interface WxMaterialCreate {
  title: string;
  content: string;
  tags?: string[] | null;
  kb_chunk_id?: number | null;
}

export interface WxMaterialListItem {
  id: number;
  title: string;
  content_preview: string;
  source_type: WxMaterialSourceType | string;
  kb_chunk_id?: number | null;
  tags?: string[] | null;
  is_used: boolean;
  created_at: string;
}

export interface WxMaterialResponse {
  id: number;
  title: string;
  content: string;
  source_type: WxMaterialSourceType | string;
  kb_chunk_id?: number | null;
  tags?: string[] | null;
  is_used: boolean;
  created_at: string;
  updated_at: string;
}

export interface WxMaterialImportFromKBRequest {
  kb_id: number;
  query: string;
  top_k?: number;
}

export interface WxMaterialImportResult {
  imported: number;
  skipped: number;
  materials: WxMaterialResponse[];
}

// === AI (outline / rewrite / expand / title) ================================

export interface WxAIOutlineRequest {
  topic: string;
  section_count?: number;
  model_config_id?: number | null;
  style?: WxAIStyle;
}

export interface WxAIOutlineResponse {
  sections: WxDraftSectionResponse[];
  llm_call_id: string;
  duration_ms: number;
}

export interface WxAIRewriteRequest {
  section_id: number;
  instruction: string;
  model_config_id?: number | null;
}

export interface WxAIRewriteResponse {
  section_id: number;
  new_content_markdown: string;
  llm_call_id: string;
  duration_ms: number;
}

export interface WxAIExpandRequest {
  section_id: number;
  expansion_ratio?: number;
  model_config_id?: number | null;
}

export interface WxAIExpandResponse {
  section_id: number;
  new_content_markdown: string;
  llm_call_id: string;
  duration_ms: number;
}

export interface WxAITitleRequest {
  count?: number;
  model_config_id?: number | null;
}

export interface WxAITitleResponse {
  titles: string[];
  llm_call_id: string;
  duration_ms: number;
}

export interface WxRenderRequest {
  template_id: number;
}

export interface WxRenderResponse {
  draft_id: number;
  content_html: string;
  preview_url: string;
}

// === Publish ================================================================

export interface WxPublishRequest {
  draft_id: number;
  account_id: number;
  scheduled_at?: string | null;
}

export interface WxPublishRecordListItem {
  id: number;
  draft_id: number;
  account_id: number;
  user_id: number;
  status: WxPublishRecordStatus | string;
  wechat_media_id?: string | null;
  wechat_msg_id?: string | null;
  scheduled_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
}

export interface WxPublishRecordResponse extends WxPublishRecordListItem {
  error_code?: string | null;
  error_message?: string | null;
  created_at: string;
}

// Internal alias — backend uses the same shape for create + request.
export type WxPublishRecordCreate = WxPublishRequest;

// AI action type used by DraftEditor's section-level action dispatch
// (e.g. "rewrite" / "expand" / "title" / "outline" / "render" passed to
// AIRewriteModal). Kept narrow on purpose — the modal branches on this.
export type AIActionType = 'rewrite' | 'expand' | 'title' | 'outline' | 'render';