// M38.2: DocumentFolder API service.
//
// Per-KB list + tree + soft delete + restore + per-doc move. Mirrors
// the backend envelope contract — see CLAUDE.md § 2 / § 3.

import api from "./auth";
import type {
  DocumentFolder,
  DocumentFolderCreatePayload,
  DocumentFolderTreeNode,
  DocumentFolderUpdatePayload,
  DocumentMovePayload,
  FolderSoftDeleteResponse,
} from "@/types/folder";
import type { ApiResponse } from "@/types/api";

interface ListFoldersParams {
  /** false = flat list (default); true = nested DocumentFolderTreeNode. */
  tree?: boolean;
}

export async function listFolders(
  kbId: number,
  params: ListFoldersParams = {},
): Promise<ApiResponse<DocumentFolder[] | DocumentFolderTreeNode[]>> {
  const res = await api.get(`/api/v1/knowledge/${kbId}/folders`, { params });
  return res.data as ApiResponse<DocumentFolder[] | DocumentFolderTreeNode[]>;
}

export async function createFolder(
  kbId: number,
  payload: DocumentFolderCreatePayload,
): Promise<ApiResponse<DocumentFolder>> {
  const res = await api.post(`/api/v1/knowledge/${kbId}/folders`, payload);
  return res.data as ApiResponse<DocumentFolder>;
}

export async function getFolder(
  folderId: number,
): Promise<ApiResponse<DocumentFolder>> {
  const res = await api.get(`/api/v1/folders/${folderId}`);
  return res.data as ApiResponse<DocumentFolder>;
}

export async function updateFolder(
  folderId: number,
  payload: DocumentFolderUpdatePayload,
): Promise<ApiResponse<DocumentFolder>> {
  const res = await api.put(`/api/v1/folders/${folderId}`, payload);
  return res.data as ApiResponse<DocumentFolder>;
}

export async function softDeleteFolder(
  folderId: number,
): Promise<FolderSoftDeleteResponse> {
  const res = await api.delete(`/api/v1/folders/${folderId}`);
  return res.data as FolderSoftDeleteResponse;
}

export async function restoreFolder(
  folderId: number,
): Promise<ApiResponse<DocumentFolder>> {
  const res = await api.post(`/api/v1/folders/${folderId}/restore`);
  return res.data as ApiResponse<DocumentFolder>;
}

export async function moveDocument(
  documentId: number,
  payload: DocumentMovePayload,
): Promise<{ moved: boolean }> {
  const res = await api.post(
    `/api/v1/knowledge/documents/${documentId}/move`,
    payload,
  );
  return res.data as { moved: boolean };
}