// M38.2.x v2: workspace permission hook.
//
// 提供 ``useCurrentUserWorkspacePermissions()`` 一次拉当前 user 在所有可见
// workspace 上的 effective permission set,缓存 key 为 ``["auth-me-workspaces"]``,
// login 后由 React Query 自动失效 / 5 分钟 stale window。
//
// ``useCanI(permission, workspaceId)`` 是便捷 hook,内部展开 implication 链:
// owner / admin bypass 之后,返回 user 在该 workspace 上是否拥有 permission。

"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  effectivePerms,
  fetchMyWorkspacePermissions,
} from "@/services/workspacePermissions";
import type {
  WorkspacePermission,
} from "@/types/workspaceMember";

/** 缓存 30 秒 stale window;用户调 transfer-ownership 后由调用方 invalidate。 */
const STALE_TIME_MS = 30_000;

export interface WorkspacePermissionsData {
  /** ``{workspace_id: effective permission set}`` — 含 owner / admin 全 perm 展开。 */
  byWorkspace: Map<number, Set<WorkspacePermission>>;
  /** 哪些 workspace 由 current user 当 owner(spec §6.5 owner auto all perm)。 */
  ownedWorkspaceIds: Set<number>;
  isLoading: boolean;
  error: Error | null;
  refetch: () => void;
}

/** 一次性拉当前 user 在所有可见 workspace 上的 effective permission set。 */
export function useCurrentUserWorkspacePermissions(): WorkspacePermissionsData {
  const query = useQuery({
    queryKey: ["auth-me-workspaces"],
    queryFn: () => fetchMyWorkspacePermissions(),
    staleTime: STALE_TIME_MS,
  });

  const data = useMemo(() => {
    const byWorkspace = new Map<number, Set<WorkspacePermission>>();
    const ownedWorkspaceIds = new Set<number>();
    if (query.data) {
      for (const entry of query.data.workspaces ?? []) {
        byWorkspace.set(
          entry.workspace_id,
          effectivePerms(entry.permissions ?? []),
        );
        if (entry.is_owner) ownedWorkspaceIds.add(entry.workspace_id);
      }
    }
    return { byWorkspace, ownedWorkspaceIds };
  }, [query.data]);

  return {
    byWorkspace: data.byWorkspace,
    ownedWorkspaceIds: data.ownedWorkspaceIds,
    isLoading: query.isLoading,
    error: query.error as Error | null,
    refetch: () => {
      query.refetch();
    },
  };
}

/** 便捷 hook:判断 user 在指定 workspace 上是否有 permission。 */
export function useCanI(
  permission: WorkspacePermission,
  workspaceId: number | null | undefined,
): boolean {
  const { byWorkspace } = useCurrentUserWorkspacePermissions();
  if (!workspaceId) return false;
  const perms = byWorkspace.get(workspaceId);
  if (!perms) return false;
  return perms.has(permission);
}

/** 批量权限判定(用于多 button 一起 disable)。 */
export function usePermissions(
  workspaceId: number | null | undefined,
): {
  has: (p: WorkspacePermission) => boolean;
  hasAny: (ps: WorkspacePermission[]) => boolean;
  hasAll: (ps: WorkspacePermission[]) => boolean;
} {
  const { byWorkspace } = useCurrentUserWorkspacePermissions();
  const perms = workspaceId ? byWorkspace.get(workspaceId) : null;
  return useMemo(
    () => ({
      has: (p: WorkspacePermission) => perms?.has(p) ?? false,
      hasAny: (ps: WorkspacePermission[]) => ps.some((p) => perms?.has(p) ?? false),
      hasAll: (ps: WorkspacePermission[]) => ps.every((p) => perms?.has(p) ?? false),
    }),
    [perms],
  );
}