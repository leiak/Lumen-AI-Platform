// M38.2.x v2: workspace member / RBAC permission service.
//
// Endpoints:
//   GET    /workspaces/{id}/members           列出 members + 每人权限
//   POST   /workspaces/{id}/members           邀请 user(整组权限)
//   PUT    /workspaces/{id}/members/{user_id} 改 user 的权限(整组覆盖)
//   DELETE /workspaces/{id}/members/{user_id} 移除 user
//   POST   /workspaces/{id}/transfer-ownership 转让 owner
//   GET    /auth/me/workspaces                当前 user 在各 ws 上的 effective 权限
//
// Envelope 解析走 ``ApiResponse.data``(SingleResponse)和 ``PaginatedResponse``;
// 4xx 错误 message 用 project-shared extractErrorMessage helper。

import api from "./auth";
import type {
  MemberInvitePayload,
  MemberUpdatePayload,
  TransferOwnershipPayload,
  WorkspaceMember,
  WorkspaceMembersResponse,
  WorkspaceMyPermissionsResponse,
  WorkspacePermission,
} from "@/types/workspaceMember";

const WORKSPACE_BASE = (id: number) => `/workspaces/${id}/members`;
const ME_WORKSPACES = `/auth/me/workspaces`;

function unwrap<T>(promise: Promise<{ data: any }>): T {
  return promise.then((res) => {
    if (res.data?.code === 200) return res.data.data as T;
    throw new Error(extractErrorMessage(res.data, "request failed"));
  }) as unknown as T;
}

function extractErrorMessage(data: any, fallback: string): string {
  const detail = data?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail === "object" && typeof detail.message === "string") {
    return detail.message;
  }
  if (typeof data?.message === "string" && data.message) return data.message;
  return fallback;
}

export async function listMembers(
  workspaceId: number,
): Promise<WorkspaceMembersResponse> {
  return unwrap<WorkspaceMembersResponse>(
    api.get(`/api/v1${WORKSPACE_BASE(workspaceId)}`),
  );
}

export async function inviteMember(
  workspaceId: number,
  payload: MemberInvitePayload,
): Promise<WorkspaceMember> {
  return unwrap<WorkspaceMember>(
    api.post(`/api/v1${WORKSPACE_BASE(workspaceId)}`, payload),
  );
}

export async function updateMember(
  workspaceId: number,
  userId: number,
  payload: MemberUpdatePayload,
): Promise<WorkspaceMember> {
  return unwrap<WorkspaceMember>(
    api.put(`/api/v1${WORKSPACE_BASE(workspaceId)}/${userId}`, payload),
  );
}

export async function removeMember(
  workspaceId: number,
  userId: number,
): Promise<{ removed: boolean }> {
  return unwrap<{ removed: boolean }>(
    api.delete(`/api/v1${WORKSPACE_BASE(workspaceId)}/${userId}`),
  );
}

export async function transferOwnership(
  workspaceId: number,
  payload: TransferOwnershipPayload,
): Promise<{ workspace_id: number; owner_id: number }> {
  return unwrap<{ workspace_id: number; owner_id: number }>(
    api.post(`/api/v1/workspaces/${workspaceId}/transfer-ownership`, payload),
  );
}

export async function fetchMyWorkspacePermissions(): Promise<WorkspaceMyPermissionsResponse> {
  return unwrap<WorkspaceMyPermissionsResponse>(api.get(`/api/v1${ME_WORKSPACES}`));
}

/** 在 client 侧展开 implication 链(与后端 _PERM_IMPLIES 镜像)。 */
export function effectivePerms(
  granted: Iterable<WorkspacePermission>,
): Set<WorkspacePermission> {
  const out = new Set<WorkspacePermission>(granted);
  // 反复迭代直到不变,处理传递闭包
  let changed = true;
  while (changed) {
    changed = false;
    for (const p of Array.from(out)) {
      const implied = PERMISSION_IMPLIES[p] ?? [];
      for (const i of implied) {
        if (!out.has(i)) {
          out.add(i);
          changed = true;
        }
      }
    }
  }
  return out;
}

/** Implication 链 —— 与 backend lumen_services/permission_service._PERM_IMPLIES 镜像。 */
const PERMISSION_IMPLIES: Partial<Record<WorkspacePermission, WorkspacePermission[]>> = {
  "workspace.update": ["workspace.read"],
  "workspace.delete": ["workspace.read"],
  "workspace.manage_members": ["workspace.read"],
  "workspace.transfer_ownership": ["workspace.read"],
  "kb.create": ["kb.read"],
  "kb.update": ["kb.read"],
  "kb.delete": ["kb.read"],
  "kb.read": ["document.read"],
  "folder.create": ["folder.read"],
  "folder.update": ["folder.read"],
  "folder.delete": ["folder.read"],
  "folder.restore": ["folder.read"],
  "document.create": ["document.read"],
  "document.update": ["document.read"],
  "document.delete": ["document.read"],
  "document.move": ["folder.read", "folder.update"],
};

/** 判断 user 在指定 workspace 上是否拥有指定 permission(含 effective 展开)。 */
export function userHasPermission(
  granted: Iterable<WorkspacePermission>,
  permission: WorkspacePermission,
): boolean {
  return effectivePerms(granted).has(permission);
}