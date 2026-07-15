import api from "./auth";
import type { ApiResponse, PaginatedResponse } from "@/types/api";

export interface User {
  id: number;
  username: string;
  email: string;
  full_name?: string;
  tenant_id: number;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
}

/** 极简版 user(无 tenant_id / is_active / is_superuser / created_at),
 * 给 owner_select 之类的下拉用。Backend: GET /api/v1/users/assignable。 */
export interface UserSimple {
  id: number;
  username: string;
  email: string;
  full_name?: string | null;
}

/** ``usersApi.assignable()`` 的解包结果(与 ``customerApi.list`` 同款)。 */
export interface AssignableUsersResult {
  items: UserSimple[];
  total: number;
  page: number;
  page_size: number;
}

export const usersApi = {
  list: (page = 1, pageSize = 10) =>
    api.get<any>(`/users/?page=${page}&page_size=${pageSize}`),
  get: (id: number) => api.get<ApiResponse<User>>(`/users/${id}`),
  create: (data: { username: string; email: string; password: string; full_name?: string }) =>
    api.post<ApiResponse<User>>("/users/", data),
  update: (id: number, data: Partial<User>) =>
    api.put<ApiResponse<User>>(`/users/${id}`, data),
  delete: (id: number) => api.delete(`/users/${id}`),

  /** GET /users/assignable — 当前租户内 active 用户(简化字段,任何已认证用户可调)。
   * 用于「客户 owner」「任务 assignee」之类下拉,避免 403 普通用户也能选同租户同事。 */
  async assignable(
    page = 1,
    pageSize = 100,
  ): Promise<AssignableUsersResult> {
    const res = await api.get<PaginatedResponse<UserSimple>>(
      `/users/assignable?page=${page}&page_size=${pageSize}`,
    );
    if (res.data?.code === 200) {
      return {
        items: res.data.data ?? [],
        total: res.data.total ?? 0,
        page: res.data.page ?? page,
        page_size: res.data.page_size ?? pageSize,
      };
    }
    throw new Error(res.data?.message || "list assignable users failed");
  },
};
