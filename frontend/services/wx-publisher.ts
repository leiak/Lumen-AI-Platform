// frontend/services/wx-publisher.ts
// M32 — 公众号助手 (WeChat Publisher) service layer.
//
// Mirrors backend 26 endpoints under /api/v1/wx-publisher/* (see spec
// docs/superpowers/specs/2026-06-17-wx-publisher-design.md §4.1).
//
// Conventions (matches services/image-generation.ts):
// - List endpoints unwrap the `PaginatedResponse<T>` envelope into a flat
//   `{ items, total, page, page_size }` shape so callers stay ergonomic.
// - Detail/create/update endpoints unwrap `SingleResponse<T>` and throw on
//   non-200.
// - DELETE returns true on 204 (backend uses 204 No Content for hard delete
//   of materials, 200 for soft delete of drafts).
// - Thumbnail endpoints stream binary — caller's responsibility to fetch +
//   blob + URL.createObjectURL (see image-generation service for the same
//   auth caveat).
//
// Token comes from the `services/auth.ts` axios interceptor — no manual
// `Authorization` header is set here.

import api from "./auth";
import type {
  WxAccountCreate,
  WxAccountUpdate,
  WxAccountDetail,
  WxAccountResponse,
  WxAccountPurgeResponse,
  WxAccountVerifyResponse,
  WxTemplateCreate,
  WxTemplateUpdate,
  WxTemplateListItem,
  WxTemplateDetail,
  WxTemplateResponse,
  WxDraftCreate,
  WxDraftUpdate,
  WxDraftListItem,
  WxDraftResponse,
  WxDraftDetail,
  WxDraftSectionCreate,
  WxDraftSectionUpdate,
  WxDraftSectionResponse,
  WxDraftSectionReorderRequest,
  WxMaterialCreate,
  WxMaterialListItem,
  WxMaterialResponse,
  WxMaterialImportFromKBRequest,
  WxMaterialImportResult,
  WxAIOutlineRequest,
  WxAIOutlineResponse,
  WxAIRewriteRequest,
  WxAIRewriteResponse,
  WxAIExpandRequest,
  WxAIExpandResponse,
  WxAITitleRequest,
  WxAITitleResponse,
  WxRenderRequest,
  WxRenderResponse,
  WxTemplateDetail,
  WxDraftPasteHtmlRequest,
  WxPublishRequest,
  WxPublishRecordListItem,
  WxPublishRecordResponse,
} from "@/types/wx-publisher";

// Generic list params (used by all list endpoints).
export interface WxListParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  category?: string;
  template_id?: number;
  account_id?: number;
  source_type?: string;
  tag?: string;
}

// Flat list shape returned by service.list() callers.
export interface WxListResult<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// Helper — unwraps the PaginatedResponse envelope. Backend returns
// { code, message, data: T[], total, page, page_size } at the axios
// res.data level (note: not nested under res.data.data for paginated —
// see `PaginatedResponse` in frontend/types/api.ts).
async function unwrapPaginated<T>(
  promise: Promise<{ data: any }>,
  fallbackPage: number,
  fallbackPageSize: number
): Promise<WxListResult<T>> {
  const res = await promise;
  if (res.data?.code === 200) {
    const body = res.data;
    return {
      items: (body.data ?? []) as T[],
      total: body.total ?? 0,
      page: body.page ?? fallbackPage,
      page_size: body.page_size ?? fallbackPageSize,
    };
  }
  throw new Error(extractErrorMessage(res.data, "list failed"));
}

// Helper — unwraps a SingleResponse envelope and returns T.
//
// 错误消息解析顺序:res.data.message(项目标准信封)→ res.data.detail(FastAPI
// HTTPException 4xx/5xx 返的形状,可能是字符串也可能是 dict)→ 兜底 "request failed"。
// 修 2026-08-07 dev 体验:发布已发布草稿返 409 时 detail 是结构化 dict
// (含 status / published_at),这里把 dict.message 提出来,让 toast 直接
// 显示「draft is in 'published' state, cannot republish」而不是「Request failed
// with status code 409」。
function extractErrorMessage(data: any, fallback: string): string {
  const detail = data?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail === "object" && typeof detail.message === "string") {
    return detail.message;
  }
  if (typeof data?.message === "string" && data.message) return data.message;
  return fallback;
}

async function unwrapSingle<T>(promise: Promise<{ data: any }>): Promise<T> {
  const res = await promise;
  if (res.data?.code === 200) return res.data.data as T;
  throw new Error(extractErrorMessage(res.data, "request failed"));
}

// === Accounts ===============================================================

export const accountApi = {
  /** GET /wx-publisher/accounts */
  list: (params: WxListParams = {}) =>
    unwrapPaginated<WxAccountResponse>(
      api.get("/wx-publisher/accounts", { params }),
      params.page ?? 1,
      params.page_size ?? 10
    ),

  /** GET /wx-publisher/accounts/{id} */
  get: (id: number) =>
    unwrapSingle<WxAccountDetail>(api.get(`/wx-publisher/accounts/${id}`)),

  /** POST /wx-publisher/accounts/ — returns full row with masked secret. */
  create: (data: WxAccountCreate) =>
    unwrapSingle<WxAccountResponse>(api.post("/wx-publisher/accounts/", data)),

  /** PUT /wx-publisher/accounts/{id} */
  update: (id: number, data: WxAccountUpdate) =>
    unwrapSingle<WxAccountResponse>(api.put(`/wx-publisher/accounts/${id}`, data)),

  /** DELETE /wx-publisher/accounts/{id} (soft delete). */
  delete: async (id: number): Promise<true> => {
    const res = await api.delete(`/wx-publisher/accounts/${id}`);
    if (res.data?.code === 200 || res.status === 204) return true;
    throw new Error(res.data?.message || "delete failed");
  },

  /** POST /wx-publisher/accounts/{id}/verify */
  verify: (id: number) =>
    unwrapSingle<WxAccountVerifyResponse>(
      api.post(`/wx-publisher/accounts/${id}/verify`, {})
    ),

  /** POST /wx-publisher/accounts/{id}/purge — admin-only hard delete.
   * Wipes the account row + every wx_publish_records referencing it.
   * wx_drafts.account_id is auto-nulled via FK SET NULL. */
  purge: (id: number) =>
    unwrapSingle<WxAccountPurgeResponse>(
      api.post(`/wx-publisher/accounts/${id}/purge`, {})
    ),
};

// === Templates ==============================================================

export const templateApi = {
  /** GET /wx-publisher/templates */
  list: (params: WxListParams = {}) =>
    unwrapPaginated<WxTemplateListItem>(
      api.get("/wx-publisher/templates", { params }),
      params.page ?? 1,
      params.page_size ?? 12
    ),

  /** GET /wx-publisher/templates/{id} */
  get: (id: number) =>
    unwrapSingle<WxTemplateDetail>(api.get(`/wx-publisher/templates/${id}`)),

  /** POST /wx-publisher/templates */
  create: (data: WxTemplateCreate) =>
    unwrapSingle<WxTemplateResponse>(api.post("/wx-publisher/templates/", data)),

  /** PUT /wx-publisher/templates/{id} */
  update: (id: number, data: WxTemplateUpdate) =>
    unwrapSingle<WxTemplateResponse>(api.put(`/wx-publisher/templates/${id}`, data)),

  /** DELETE /wx-publisher/templates/{id} (system templates return 403). */
  delete: async (id: number): Promise<true> => {
    const res = await api.delete(`/wx-publisher/templates/${id}`);
    if (res.data?.code === 200 || res.status === 204) return true;
    throw new Error(res.data?.message || "delete failed");
  },

  /** POST /wx-publisher/templates/{id}/generate-thumbnail — M32.1
   * 用 image-generation API 自动生成模板缩略图 (同步, max 60s).
   * 返回更新后的模板详情 (thumbnail 已写入). */
  generateThumbnail: (id: number) =>
    unwrapSingle<WxTemplateDetail>(
      api.post(`/wx-publisher/templates/${id}/generate-thumbnail`)
    ),

  /** Path to the thumbnail bytes endpoint. Auth header NOT auto-set on
   *  plain <img src>; consumer must fetch + blob + createObjectURL. */
  thumbnailPath: (id: number) => `/wx-publisher/templates/${id}/thumbnail`,
};

// === Drafts =================================================================

export const draftApi = {
  /** GET /wx-publisher/drafts */
  list: (params: WxListParams = {}) =>
    unwrapPaginated<WxDraftListItem>(
      api.get("/wx-publisher/drafts", { params }),
      params.page ?? 1,
      params.page_size ?? 10
    ),

  /** GET /wx-publisher/drafts/{id} — full detail incl. sections[] */
  get: (id: number) =>
    unwrapSingle<WxDraftDetail>(api.get(`/wx-publisher/drafts/${id}`)),

  /** POST /wx-publisher/drafts */
  create: (data: WxDraftCreate) =>
    unwrapSingle<WxDraftResponse>(api.post("/wx-publisher/drafts/", data)),

  /** PUT /wx-publisher/drafts/{id} */
  update: (id: number, data: WxDraftUpdate) =>
    unwrapSingle<WxDraftResponse>(api.put(`/wx-publisher/drafts/${id}`, data)),

  /** DELETE /wx-publisher/drafts/{id} (soft delete). */
  delete: async (id: number): Promise<true> => {
    const res = await api.delete(`/wx-publisher/drafts/${id}`);
    if (res.data?.code === 200 || res.status === 204) return true;
    throw new Error(res.data?.message || "delete failed");
  },

  // --- Sections --------------------------------------------------------------

  /** POST /wx-publisher/drafts/{id}/sections */
  addSection: (draftId: number, data: WxDraftSectionCreate) =>
    unwrapSingle<WxDraftSectionResponse>(
      api.post(`/wx-publisher/drafts/${draftId}/sections`, data)
    ),

  /** PUT /wx-publisher/drafts/{id}/sections/{sid} */
  updateSection: (draftId: number, sectionId: number, data: WxDraftSectionUpdate) =>
    unwrapSingle<WxDraftSectionResponse>(
      api.put(`/wx-publisher/drafts/${draftId}/sections/${sectionId}`, data)
    ),

  /** DELETE /wx-publisher/drafts/{id}/sections/{sid} */
  deleteSection: async (draftId: number, sectionId: number): Promise<true> => {
    const res = await api.delete(
      `/wx-publisher/drafts/${draftId}/sections/${sectionId}`
    );
    if (res.data?.code === 200 || res.status === 204) return true;
    throw new Error(res.data?.message || "delete section failed");
  },

  /** POST /wx-publisher/drafts/{id}/sections/reorder */
  reorderSections: (draftId: number, data: WxDraftSectionReorderRequest) =>
    unwrapSingle<WxDraftSectionResponse[]>(
      api.post(`/wx-publisher/drafts/${draftId}/sections/reorder`, data)
    ),

  /** POST /wx-publisher/drafts/{id}/paste-html — M32.1 粘贴 HTML → MD (飞书/网页) */
  pasteHtml: (id: number, data: WxDraftPasteHtmlRequest) =>
    unwrapSingle<WxDraftDetail>(
      api.post(`/wx-publisher/drafts/${id}/paste-html`, data)
    ),
};

// === AI (outline / rewrite / expand / title / render) =======================

export const draftAiApi = {
  /** POST /wx-publisher/drafts/{id}/ai/outline */
  outline: (draftId: number, data: WxAIOutlineRequest) =>
    unwrapSingle<WxAIOutlineResponse>(
      api.post(`/wx-publisher/drafts/${draftId}/ai/outline`, data)
    ),

  /** POST /wx-publisher/drafts/{id}/ai/rewrite */
  rewrite: (draftId: number, data: WxAIRewriteRequest) =>
    unwrapSingle<WxAIRewriteResponse>(
      api.post(`/wx-publisher/drafts/${draftId}/ai/rewrite`, data)
    ),

  /** POST /wx-publisher/drafts/{id}/ai/expand */
  expand: (draftId: number, data: WxAIExpandRequest) =>
    unwrapSingle<WxAIExpandResponse>(
      api.post(`/wx-publisher/drafts/${draftId}/ai/expand`, data)
    ),

  /** POST /wx-publisher/drafts/{id}/ai/title */
  title: (draftId: number, data: WxAITitleRequest) =>
    unwrapSingle<WxAITitleResponse>(
      api.post(`/wx-publisher/drafts/${draftId}/ai/title`, data)
    ),

  /** POST /wx-publisher/drafts/{id}/render */
  render: (draftId: number, data: WxRenderRequest) =>
    unwrapSingle<WxRenderResponse>(
      api.post(`/wx-publisher/drafts/${draftId}/render`, data)
    ),
};

// === Materials ==============================================================

export const materialApi = {
  /** GET /wx-publisher/materials */
  list: (params: WxListParams = {}) =>
    unwrapPaginated<WxMaterialListItem>(
      api.get("/wx-publisher/materials", { params }),
      params.page ?? 1,
      params.page_size ?? 10
    ),

  /** GET /wx-publisher/materials/{id} */
  get: (id: number) =>
    unwrapSingle<WxMaterialResponse>(api.get(`/wx-publisher/materials/${id}`)),

  /** POST /wx-publisher/materials — manual entry */
  create: (data: WxMaterialCreate) =>
    unwrapSingle<WxMaterialResponse>(api.post("/wx-publisher/materials/", data)),

  /** POST /wx-publisher/materials/from-kb — import from KB via RetrievalPipeline */
  importFromKB: (data: WxMaterialImportFromKBRequest) =>
    unwrapSingle<WxMaterialImportResult>(
      api.post("/wx-publisher/materials/from-kb", data)
    ),

  /** DELETE /wx-publisher/materials/{id} */
  delete: async (id: number): Promise<true> => {
    const res = await api.delete(`/wx-publisher/materials/${id}`);
    if (res.data?.code === 200 || res.status === 204) return true;
    throw new Error(res.data?.message || "delete failed");
  },
};

// === Publish ================================================================

export const publishApi = {
  /** POST /wx-publisher/publish/ — async; BackgroundTasks + WS notification */
  createPublish: (data: WxPublishRequest) =>
    unwrapSingle<WxPublishRecordListItem>(
      api.post("/wx-publisher/publish/", data)
    ),

  /** GET /wx-publisher/publish/{record_id} */
  getPublish: (recordId: number) =>
    unwrapSingle<WxPublishRecordResponse>(
      api.get(`/wx-publisher/publish/${recordId}`)
    ),
};

// Aggregated default export — pattern used by some pages for namespacing.
export default {
  accountApi,
  templateApi,
  draftApi,
  draftAiApi,
  materialApi,
  publishApi,
};