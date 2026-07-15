// frontend/services/text2sql.ts
// M33 — Text2SQL 智能问数 (T27)
//
// All endpoints return the project's standard envelopes:
// - SingleResponse[T]   → res.data.data
// - PaginatedResponse[T] → res.data.data (items) + res.data.total/page/page_size
//
// Auth interceptor in services/auth.ts adds the Bearer token automatically.

import api from "./auth";
import type {
  Text2SqlAskRequest,
  Text2SqlAskResponse,
  Text2SqlDataSource,
  Text2SqlDataSourceCreate,
  Text2SqlDataSourceUpdate,
  Text2SqlDetail,
  Text2SqlHistoryItem,
  Text2SqlSchemaResponse,
} from "@/types/text2sql";

export interface HistoryListParams {
  page?: number;
  page_size?: number;
  status?: string;
  keyword?: string;
}

export interface ListResult<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

function unwrapSingle<T>(res: any, fallback: string): T {
  if (res.data?.code === 200) return res.data.data as T;
  throw new Error(res.data?.message || fallback);
}

function unwrapPaginated<T>(res: any, params: any, fallback: string): ListResult<T> {
  if (res.data?.code === 200) {
    const body = res.data;
    return {
      items: (body.data ?? []) as T[],
      total: body.total ?? 0,
      page: body.page ?? params.page ?? 1,
      page_size: body.page_size ?? params.page_size ?? 20,
    };
  }
  throw new Error(res.data?.message || fallback);
}

export const text2SqlApi = {
  // ── Ask ───────────────────────────────────────────────────────
  async ask(body: Text2SqlAskRequest): Promise<Text2SqlAskResponse> {
    const res = await api.post("/text2sql/ask", body);
    return unwrapSingle<Text2SqlAskResponse>(res, "ask failed");
  },

  // ── History ───────────────────────────────────────────────────
  async listHistory(params: HistoryListParams = {}): Promise<ListResult<Text2SqlHistoryItem>> {
    const res = await api.get("/text2sql/history", { params });
    return unwrapPaginated<Text2SqlHistoryItem>(res, params, "listHistory failed");
  },

  async getHistory(id: number): Promise<Text2SqlDetail> {
    const res = await api.get(`/text2sql/history/${id}`);
    return unwrapSingle<Text2SqlDetail>(res, "getHistory failed");
  },

  async deleteHistory(id: number): Promise<void> {
    const res = await api.delete(`/text2sql/history/${id}`);
    if (res.status !== 204 && res.data?.code !== 200) {
      throw new Error(res.data?.message || "deleteHistory failed");
    }
  },

  // ── Schema ────────────────────────────────────────────────────
  async getSchema(dataSourceId: number): Promise<Text2SqlSchemaResponse> {
    const res = await api.get("/text2sql/schema", {
      params: { data_source_id: dataSourceId },
    });
    return unwrapSingle<Text2SqlSchemaResponse>(res, "getSchema failed");
  },

  // ── DataSources ───────────────────────────────────────────────
  async listDataSources(
    params: { page?: number; page_size?: number; include_inactive?: boolean } = {},
  ): Promise<ListResult<Text2SqlDataSource>> {
    const res = await api.get("/text2sql/datasources", { params });
    return unwrapPaginated<Text2SqlDataSource>(res, params, "listDataSources failed");
  },

  async createDataSource(
    body: Text2SqlDataSourceCreate,
  ): Promise<Text2SqlDataSource> {
    const res = await api.post("/text2sql/datasources", body);
    return unwrapSingle<Text2SqlDataSource>(res, "createDataSource failed");
  },

  async updateDataSource(
    id: number,
    body: Text2SqlDataSourceUpdate,
  ): Promise<Text2SqlDataSource> {
    const res = await api.put(`/text2sql/datasources/${id}`, body);
    return unwrapSingle<Text2SqlDataSource>(res, "updateDataSource failed");
  },

  async deleteDataSource(id: number): Promise<void> {
    const res = await api.delete(`/text2sql/datasources/${id}`);
    if (res.status !== 204 && res.data?.code !== 200) {
      throw new Error(res.data?.message || "deleteDataSource failed");
    }
  },
};
