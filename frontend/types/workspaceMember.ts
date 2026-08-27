// M38.2.x v2: Workspace member / RBAC permission types.
//
// Spec: docs-internal/superpowers/specs/2026-08-27-workspace-rbac.md §5.1.
// 19 个 permission token 跨 4 资源轴(workspace / kb / folder / document),
// 服务端 PermissionService 内部展开 implication 链(例 kb.update 自动含
// kb.read + document.read),前端只关心原始 19 项。

export type WorkspacePermission =
  | "workspace.read"
  | "workspace.update"
  | "workspace.delete"
  | "workspace.transfer_ownership"
  | "workspace.manage_members"
  | "kb.read"
  | "kb.create"
  | "kb.update"
  | "kb.delete"
  | "folder.read"
  | "folder.create"
  | "folder.update"
  | "folder.delete"
  | "folder.restore"
  | "document.read"
  | "document.create"
  | "document.update"
  | "document.delete"
  | "document.move";

export const ALL_PERMISSIONS: WorkspacePermission[] = [
  "workspace.read",
  "workspace.update",
  "workspace.delete",
  "workspace.transfer_ownership",
  "workspace.manage_members",
  "kb.read",
  "kb.create",
  "kb.update",
  "kb.delete",
  "folder.read",
  "folder.create",
  "folder.update",
  "folder.delete",
  "folder.restore",
  "document.read",
  "document.create",
  "document.update",
  "document.delete",
  "document.move",
];

/** 只读 4 项:用于「只读」快捷批量授权。 */
export const READ_ONLY_PERMISSIONS: WorkspacePermission[] = [
  "workspace.read",
  "kb.read",
  "folder.read",
  "document.read",
];

/** 写权限 = read + create/update/move(不含 delete / manage)。 */
export const WRITE_PERMISSIONS: WorkspacePermission[] = [
  "workspace.read",
  "workspace.update",
  "kb.read",
  "kb.create",
  "kb.update",
  "folder.read",
  "folder.create",
  "folder.update",
  "document.read",
  "document.create",
  "document.update",
  "document.move",
];

/** 单条 grant 行:某个 user 在某个 workspace 上持有的 permission。 */
export interface WorkspaceMemberPermission {
  workspace_id: number;
  user_id: number;
  permission: WorkspacePermission;
  created_at?: string;
}

/** 列出 workspace 全部成员(按 user 聚合)。 */
export interface WorkspaceMember {
  user_id: number;
  username: string;
  email?: string | null;
  full_name?: string | null;
  /** 该 user 在该 workspace 上的全部 grant 行(可能含重复 owner_id 不算)。 */
  permissions: WorkspacePermission[];
  /** 由后端 join 计算:is_owner = workspace.owner_id == user_id。 */
  is_owner: boolean;
  created_at?: string;
}

export interface MemberInvitePayload {
  user_id: number;
  /** 整组覆盖:邀请时一次性给一组权限,后续再调整。 */
  permissions: WorkspacePermission[];
}

export interface MemberUpdatePayload {
  /** 整组覆盖(POST 同形):用新集合替换旧集合,空集 = 撤销全部。 */
  permissions: WorkspacePermission[];
}

export interface TransferOwnershipPayload {
  new_owner_id: number;
}

export interface WorkspaceMembersResponse {
  members: WorkspaceMember[];
  total: number;
}

export interface WorkspaceMyPermissionsResponse {
  /** 当前 user 在各 workspace 上的 effective permission set。 */
  workspaces: Array<{
    workspace_id: number;
    permissions: WorkspacePermission[];
    is_owner: boolean;
  }>;
}