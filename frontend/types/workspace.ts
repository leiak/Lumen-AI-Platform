// M38.2: Workspace navigation root (per-tenant aggregation of KBs).
//
// Spec: docs-internal/superpowers/specs/2026-08-26-kb-workspace-folder.md
// § 3.3 — workspaces table + workspace_id FK on knowledge_bases.
//
// Identification: a workspace owns NO data (KBs hang off the tenant
// directly via the FK ON DELETE SET NULL on ``workspace_id``), so the
// workspace is purely navigation.

export interface Workspace {
  id: number;
  tenant_id: number;
  name: string;
  description?: string | null;
  owner_id?: number | null;
  icon?: string | null;
  color?: string | null;
  /** filled by list/tree endpoints via a single GROUP BY. */
  knowledge_base_count?: number;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceCreatePayload {
  name: string;
  description?: string;
  icon?: string;
  color?: string;
}

export interface WorkspaceUpdatePayload {
  name?: string;
  description?: string;
  icon?: string;
  color?: string;
}

/** Folder inside the workspace tree (depth ≤ 2 in tree response). */
export interface FolderTreeNode {
  id: number;
  name: string;
  description?: string | null;
  icon?: string | null;
  color?: string | null;
  document_count: number;
  children: FolderTreeNode[];
}

/** KB inside the workspace tree. */
export interface KnowledgeBaseTreeNode {
  id: number;
  name: string;
  description?: string | null;
  document_count: number;
  folders: FolderTreeNode[];
}

/** Single round-trip payload consumed by the sidebar. */
export interface WorkspaceTreeResponse {
  workspace: Workspace;
  knowledge_bases: KnowledgeBaseTreeNode[];
}