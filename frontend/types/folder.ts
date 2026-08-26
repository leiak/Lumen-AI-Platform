// M38.2: DocumentFolder — tree inside a single KB.
//
// Spec § 3.2 — document_folders table + self-FK parent_id for the tree.
// Soft delete via ``deleted_at`` (30-day restore window per spec § 8).

export interface DocumentFolder {
  id: number;
  knowledge_base_id: number;
  parent_id: number | null;
  name: string;
  description?: string | null;
  order_index: number;
  created_by?: number | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  /** Transient — filled in by the list/get endpoint for the sidebar. */
  document_count?: number;
  /** Transient — ancestor path like "e.g. 研发 / 后端". */
  path?: string | null;
}

export interface DocumentFolderCreatePayload {
  name: string;
  parent_id?: number | null;
  description?: string;
  order_index?: number;
}

export interface DocumentFolderUpdatePayload {
  name?: string;
  parent_id?: number | null;
  description?: string;
  order_index?: number;
}

export interface DocumentFolderTreeNode {
  id: number;
  name: string;
  description?: string | null;
  order_index: number;
  parent_id: number | null;
  document_count: number;
  children: DocumentFolderTreeNode[];
}

export interface DocumentMovePayload {
  target_folder_id: number | null;
}

export interface FolderSoftDeleteResponse {
  scanned: number;
  deleted_folders: number;
  detached_documents: number;
}