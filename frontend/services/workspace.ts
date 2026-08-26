// M38.2: workspace API service.
//
// Sidebar-friendly single round-trip tree + lightweight CRUD. Mirrors
// the backend envelope contract — see CLAUDE.md § 2 / § 3.
//
// All endpoints are tenant-scoped (or admin opt-in for the list view).

import api from "./auth";
import type {
  Workspace,
  WorkspaceCreatePayload,
  WorkspaceTreeResponse,
  WorkspaceUpdatePayload,
} from "@/types/workspace";
import type { ApiResponse, PaginatedResponse } from "@/types/api";

const BASE = "/api/v1/workspaces";

export interface ListWorkspacesParams {
  page?: number;
  page_size?: number;
  /** Admin override; ignored for non-admin callers (backend filters by JWT). */
  tenant_id?: number;
}

export async function listWorkspaces(
  params: ListWorkspacesParams = {},
): Promise<PaginatedResponse<Workspace>> {
  const res = await api.get(BASE, { params });
  return res.data as PaginatedResponse<Workspace>;
}

export async function createWorkspace(
  payload: WorkspaceCreatePayload,
): Promise<ApiResponse<Workspace>> {
  const res = await api.post(BASE, payload);
  return res.data as ApiResponse<Workspace>;
}

export async function getWorkspace(id: number): Promise<ApiResponse<Workspace>> {
  const res = await api.get(`${BASE}/${id}`);
  return res.data as ApiResponse<Workspace>;
}

export async function updateWorkspace(
  id: number,
  payload: WorkspaceUpdatePayload,
): Promise<ApiResponse<Workspace>> {
  const res = await api.put(`${BASE}/${id}`, payload);
  return res.data as ApiResponse<Workspace>;
}

export async function deleteWorkspace(id: number): Promise<{ deleted: boolean }> {
  const res = await api.delete(`${BASE}/${id}`);
  return res.data as { deleted: boolean };
}

export async function getWorkspaceTree(
  id: number,
): Promise<ApiResponse<WorkspaceTreeResponse>> {
  const res = await api.get(`${BASE}/${id}/tree`);
  return res.data as ApiResponse<WorkspaceTreeResponse>;
}