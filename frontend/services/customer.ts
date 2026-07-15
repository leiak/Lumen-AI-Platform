// frontend/services/customer.ts
// M33 — 客户管理 (CRM) service layer.
//
// Mirrors backend 16 endpoints under /api/v1/customers/* + /api/v1/customer-fields/*
// (see spec docs/superpowers/specs/2026-06-20-customer-management-design.md §4.1).
//
// Conventions (matches services/wx-publisher.ts):
// - List endpoints unwrap ``PaginatedResponse<T>`` envelope into flat
//   ``{ items, total, page, page_size }`` shape.
// - Single endpoints unwrap ``SingleResponse<T>`` and throw on non-200.
// - DELETE returns true on 204.
// - Token comes from services/auth.ts axios interceptor — no manual
//   ``Authorization`` header set here.

import api from "./auth";
import type {
  AIAdvisorRequest,
  AIAdvisorResponse,
  CustomerCreate,
  CustomerDetail,
  CustomerFieldDefinitionCreate,
  CustomerFieldDefinitionResponse,
  CustomerFieldDefinitionUpdate,
  CustomerListItem,
  CustomerListParams,
  CustomerListResult,
  CustomerUpdate,
  FollowUpCreate,
  FollowUpResponse,
  FollowUpUpdate,
  UpcomingFollowUpItem,
  UpcomingFollowUpsParams,
} from "@/types/customer";

// === Helpers ===============================================================

async function unwrapPaginated<T>(
  promise: Promise<{ data: any }>,
  fallbackPage: number,
  fallbackPageSize: number,
): Promise<CustomerListResult<T>> {
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
  throw new Error(res.data?.message || "list failed");
}

async function unwrapSingle<T>(promise: Promise<{ data: any }>): Promise<T> {
  const res = await promise;
  if (res.data?.code === 200) {
    if (res.data.data === null || res.data.data === undefined) {
      throw new Error("server returned empty data");
    }
    return res.data.data as T;
  }
  throw new Error(res.data?.message || "request failed");
}

function _toCsv<T extends string>(items: T[] | undefined): string | undefined {
  if (!items || items.length === 0) return undefined;
  return items.join(",");
}

// === Customer CRUD =========================================================

export const customerApi = {
  /** GET /customers — 多维过滤 + 分页。手机号返脱敏版。 */
  list: (params: CustomerListParams = {}) => {
    const apiParams: Record<string, unknown> = {
      page: params.page ?? 1,
      page_size: params.page_size ?? 20,
    };
    if (params.keyword) apiParams.keyword = params.keyword;
    if (params.levels?.length) apiParams.levels = _toCsv(params.levels);
    if (params.sources?.length) apiParams.sources = _toCsv(params.sources);
    if (params.owner_user_id != null) apiParams.owner_user_id = params.owner_user_id;
    if (params.industry) apiParams.industry = params.industry;
    if (params.tags?.length) apiParams.tags = _toCsv(params.tags);
    if (params.next_follow_up_before)
      apiParams.next_follow_up_before = params.next_follow_up_before;
    if (params.is_active !== undefined) apiParams.is_active = params.is_active;
    if (params.sort) apiParams.sort = params.sort;
    return unwrapPaginated<CustomerListItem>(
      api.get("/customers", { params: apiParams }),
      params.page ?? 1,
      params.page_size ?? 20,
    );
  },

  /** GET /customers/{id} — 详情,手机号完整 + custom_fields schema 解析。 */
  get: (id: number) =>
    unwrapSingle<CustomerDetail>(api.get(`/customers/${id}`)),

  /** POST /customers */
  create: (data: CustomerCreate) =>
    unwrapSingle<CustomerDetail>(api.post("/customers", data)),

  /** PUT /customers/{id} */
  update: (id: number, data: CustomerUpdate) =>
    unwrapSingle<CustomerDetail>(api.put(`/customers/${id}`, data)),

  /** DELETE /customers/{id} — 软删。 */
  delete: async (id: number): Promise<true> => {
    const res = await api.delete(`/customers/${id}`);
    if (res.status === 204) return true;
    throw new Error(res.data?.message || "delete failed");
  },

  /** POST /customers/{id}/restore */
  restore: (id: number) =>
    unwrapSingle<CustomerDetail>(api.post(`/customers/${id}/restore`, {})),

  // --- Upcoming follow-ups --------------------------------------------------

  /** GET /customers/upcoming-follow-ups — 我的待跟进。 */
  upcomingFollowUps: (params: UpcomingFollowUpsParams = {}) => {
    const apiParams: Record<string, unknown> = {
      page: params.page ?? 1,
      page_size: params.page_size ?? 20,
    };
    if (params.owner_user_id != null) apiParams.owner_user_id = params.owner_user_id;
    if (params.days != null) apiParams.days = params.days;
    return unwrapPaginated<UpcomingFollowUpItem>(
      api.get("/customers/upcoming-follow-ups", { params: apiParams }),
      params.page ?? 1,
      params.page_size ?? 20,
    );
  },

  // --- Follow-ups ------------------------------------------------------------

  /** GET /customers/{id}/follow-ups — 跟进 timeline。 */
  listFollowUps: (customerId: number, page = 1, pageSize = 20) =>
    unwrapPaginated<FollowUpResponse>(
      api.get(`/customers/${customerId}/follow-ups`, {
        params: { page, page_size: pageSize },
      }),
      page,
      pageSize,
    ),

  /** POST /customers/{id}/follow-ups — 创建跟进。 */
  createFollowUp: (customerId: number, data: FollowUpCreate) =>
    unwrapSingle<FollowUpResponse>(
      api.post(`/customers/${customerId}/follow-ups`, data),
    ),

  /** PUT /customers/{id}/follow-ups/{fid} — 更新跟进。 */
  updateFollowUp: (
    customerId: number,
    followUpId: number,
    data: FollowUpUpdate,
  ) =>
    unwrapSingle<FollowUpResponse>(
      api.put(`/customers/${customerId}/follow-ups/${followUpId}`, data),
    ),

  /** DELETE /customers/{id}/follow-ups/{fid} — 物理删除。 */
  deleteFollowUp: async (
    customerId: number,
    followUpId: number,
  ): Promise<true> => {
    const res = await api.delete(
      `/customers/${customerId}/follow-ups/${followUpId}`,
    );
    if (res.status === 204) return true;
    throw new Error(res.data?.message || "delete follow-up failed");
  },

  // --- AI advisor ------------------------------------------------------------

  /** POST /customers/{id}/ai/suggest — AI 智能建议(同步,5-15s)。 */
  aiSuggest: (customerId: number, data: AIAdvisorRequest) =>
    unwrapSingle<AIAdvisorResponse>(
      api.post(`/customers/${customerId}/ai/suggest`, data),
    ),
};

// === Customer Field Definition CRUD ========================================

export const customerFieldApi = {
  /** GET /customer-fields — 字段定义列表。 */
  list: (page = 1, pageSize = 100, includeInactive = false) =>
    unwrapPaginated<CustomerFieldDefinitionResponse>(
      api.get("/customer-fields", {
        params: { page, page_size: pageSize, include_inactive: includeInactive },
      }),
      page,
      pageSize,
    ),

  /** POST /customer-fields */
  create: (data: CustomerFieldDefinitionCreate) =>
    unwrapSingle<CustomerFieldDefinitionResponse>(
      api.post("/customer-fields", data),
    ),

  /** PUT /customer-fields/{id} */
  update: (id: number, data: CustomerFieldDefinitionUpdate) =>
    unwrapSingle<CustomerFieldDefinitionResponse>(
      api.put(`/customer-fields/${id}`, data),
    ),

  /** DELETE /customer-fields/{id} */
  delete: async (id: number): Promise<true> => {
    const res = await api.delete(`/customer-fields/${id}`);
    if (res.status === 204) return true;
    throw new Error(res.data?.message || "delete field failed");
  },
};

export default {
  customerApi,
  customerFieldApi,
};