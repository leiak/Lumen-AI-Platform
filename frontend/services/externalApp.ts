import api from "./auth";
import type {
  ApiResponse,
  ExternalApp,
  ExternalAppCreated,
  ExternalAppUsage,
  ExternalAppCreateRequest,
  ExternalAppUpdateRequest,
} from "@/types/api";

// Transformed list shape for callers (matches plan's Paginated<T> idea but
// consumed from the backend's flat PaginatedResponse envelope).
export interface ExternalAppList {
  items: ExternalApp[];
  total: number;
  page: number;
  page_size: number;
}

export const externalAppApi = {
  list: (params: { page?: number; page_size?: number; search?: string } = {}) =>
    api
      .get<ApiResponse<ExternalApp[]> & { total: number; page: number; page_size: number }>(
        "/external-apps",
        { params }
      )
      .then((r) => ({
        items: r.data.data ?? [],
        total: r.data.total ?? 0,
        page: r.data.page ?? 1,
        page_size: r.data.page_size ?? 20,
      })),

  get: (id: number) =>
    api
      .get<ApiResponse<ExternalApp>>(`/external-apps/${id}`)
      .then((r) => r.data.data as ExternalApp),

  create: (body: ExternalAppCreateRequest) =>
    api
      .post<ApiResponse<ExternalAppCreated>>("/external-apps", body)
      .then((r) => r.data.data as ExternalAppCreated),

  update: (id: number, body: ExternalAppUpdateRequest) =>
    api
      .patch<ApiResponse<ExternalApp>>(`/external-apps/${id}`, body)
      .then((r) => r.data.data as ExternalApp),

  remove: (id: number) =>
    api
      .delete<ApiResponse<null>>(`/external-apps/${id}`)
      .then((r) => ({ code: r.data.code, message: r.data.message ?? "" })),

  regenerateSecret: (id: number) =>
    api
      .post<ApiResponse<ExternalAppCreated>>(`/external-apps/${id}/regenerate-secret`)
      .then((r) => r.data.data as ExternalAppCreated),

  usage: (id: number) =>
    api
      .get<ApiResponse<ExternalAppUsage>>(`/external-apps/${id}/usage`)
      .then((r) => r.data.data as ExternalAppUsage),
};

// Lightweight option lists for the whitelist Selects in [id]/page.tsx and
// new/page.tsx. We pull the full page_size=999 list and rely on AntD
// Select's default client-side filterOption for search — the backend's
// AgentService.list_agents / TeamService.list_teams do not implement
// server-side search, so keeping it client-side is the simplest path.
// (If agents grow past a few thousand we can switch to server-side search
// in a follow-up.)
export interface AgentOption {
  id: number;
  name: string;
}

export async function listAgentOptions(): Promise<AgentOption[]> {
  const res = await api.get<ApiResponse<{ id: number; name: string }[]>>(
    "/agents",
    { params: { page: 1, page_size: 999 } }
  );
  if (res.data.code !== 200) {
    throw new Error(res.data.message ?? "list agents failed");
  }
  return (res.data.data ?? []).map((a) => ({ id: a.id, name: a.name }));
}

export interface TeamOption {
  id: number;
  name: string;
}

export async function listTeamOptions(): Promise<TeamOption[]> {
  const res = await api.get<ApiResponse<{ id: number; name: string }[]>>(
    "/agent-teams",
    { params: { page: 1, page_size: 999 } }
  );
  if (res.data.code !== 200) {
    throw new Error(res.data.message ?? "list teams failed");
  }
  return (res.data.data ?? []).map((t) => ({ id: t.id, name: t.name }));
}

