"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { message } from "antd";

import { knowledgeApi } from "@/services/knowledge";
import {
  createWorkspace,
  getWorkspaceTree,
  listWorkspaces,
} from "@/services/workspace";
import {
  createFolder,
  listFolders,
  moveDocument,
  updateFolder,
} from "@/services/folder";
import type { Workspace, WorkspaceTreeResponse } from "@/types/workspace";
import type { DocumentFolderTreeNode } from "@/types/folder";
import type { KnowledgeBase } from "@/types/api";
import type { DocumentResponse } from "@/services/knowledge";

/**
 * M40.1 Phase 1 / 6: workspace → KB → folder 三层 sidebar navigation + 4 个 modal。
 *
 * 把 page.tsx 里以下内容搬过来:
 * - selectedWorkspaceId / selectedFolderId / currentUserId(读 localStorage)
 * - 4 个 modal open flag(createWsOpen / createFolderOpen / moveDocOpen / membersOpen)
 * - 4 个 useQuery(workspaces / ungroupedTree / workspaceTrees / folderTree)
 * - 6 个 handler(handleSelectWorkspace / handleSelectKb / handleSelectFolder /
 *   handleCreateWorkspace / handleCreateFolder / handleMoveDocument /
 *   handleMoveKbDrag / handleMoveFolderDrag)
 *
 * KB 选择(selectedKB)由 page 层持有,hook 通过 onKbChange 回调通知;不把 KB state
 * 收进来是为了不让 workspace hook 跟 KB CRUD hook 耦合。
 *
 * fetchDocuments / searchResults / searchQuery 这些文档+搜索状态属于 useDocumentList
 * / useDocumentSearch,不在本 hook 范围。
 */
export interface UseWorkspaceTreeArgs {
  /** 当前选中的 KB(由 useKnowledgeList 持有),用于 onSelectFolder 时同步 selectedKB */
  selectedKB: KnowledgeBase | null;
  /** 通知 page KB 已切换(由 page 接 → fetchDocuments / 清 search 结果 / setSelectedFolderId(null)) */
  onKbChange: (kb: KnowledgeBase | null) => void;
}

export interface UseWorkspaceTreeReturn {
  // selection state
  selectedWorkspaceId: number | null;
  setSelectedWorkspaceId: (v: number | null) => void;
  selectedFolderId: number | null;
  setSelectedFolderId: (v: number | null) => void;
  currentUserId: number;

  // queries(给 page / 子组件读)
  workspaces: Workspace[];
  treesByWorkspace: Record<number, WorkspaceTreeResponse | null>;
  workspaceTreeLoading: boolean;
  folderTree: DocumentFolderTreeNode[];
  refetchFolders: () => void;

  // modal open flag + 移动中的 doc
  createWsOpen: boolean;
  setCreateWsOpen: (v: boolean) => void;
  createFolderOpen: boolean;
  setCreateFolderOpen: (v: boolean) => void;
  moveDocOpen: boolean;
  setMoveDocOpen: (v: boolean) => void;
  movingDoc: DocumentResponse | null;
  setMovingDoc: (v: DocumentResponse | null) => void;
  membersOpen: boolean;
  setMembersOpen: (v: boolean) => void;

  // handlers
  handleSelectWorkspace: (workspaceId: number | null) => void;
  handleSelectKb: (
    workspaceId: number | null,
    kbId: number | null
  ) => Promise<void>;
  handleSelectFolder: (
    workspaceId: number | null,
    kbId: number,
    folderId: number | null
  ) => Promise<void>;
  handleCreateWorkspace: (payload: {
    name: string;
    description?: string;
    icon?: string;
    color?: string;
  }) => Promise<void>;
  handleCreateFolder: (payload: {
    name: string;
    parent_id?: number | null;
    description?: string;
    order_index?: number;
  }) => Promise<void>;
  handleMoveDocument: (payload: {
    target_folder_id: number | null;
  }) => Promise<void>;
  handleMoveKbDrag: (
    kbId: number,
    targetWorkspaceId: number | null
  ) => Promise<void>;
  handleMoveFolderDrag: (
    folderId: number,
    targetParentId: number | null,
    targetKbId: number | null
  ) => Promise<void>;
}

export function useWorkspaceTree(
  args: UseWorkspaceTreeArgs
): UseWorkspaceTreeReturn {
  const { selectedKB, onKbChange } = args;
  const queryClient = useQueryClient();

  // ──────────── selection state ────────────
  // selectedWorkspaceId = null 表示「未分组」(workspace_id IS NULL)
  // selectedFolderId = null 表示「KB 根目录」(folder_id=0)
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<
    number | null
  >(null);
  const [selectedFolderId, setSelectedFolderId] = useState<number | null>(
    null
  );

  // ──────────── modal open flag + moving doc ────────────
  const [createWsOpen, setCreateWsOpen] = useState(false);
  const [createFolderOpen, setCreateFolderOpen] = useState(false);
  const [moveDocOpen, setMoveDocOpen] = useState(false);
  const [movingDoc, setMovingDoc] = useState<DocumentResponse | null>(null);
  const [membersOpen, setMembersOpen] = useState(false);

  // ──────────── current user id (M38.2.x v2:owner 比较) ────────────
  const [currentUserId, setCurrentUserId] = useState<number>(0);
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = localStorage.getItem("user");
      if (raw) {
        const parsed = JSON.parse(raw);
        if (typeof parsed?.id === "number") setCurrentUserId(parsed.id);
      }
    } catch {
      // 静默:不阻塞 UI
    }
  }, []);

  // ──────────── 4 个 useQuery ────────────
  // 1. workspaces 列表(sidebar enumeration)
  const { data: workspacesResp } = useQuery({
    queryKey: ["workspaces", "list"],
    queryFn: () => listWorkspaces({ page: 1, page_size: 100 }),
  });
  const workspaces = workspacesResp?.data || [];

  // 2. 未分组桶的 tree(workspace_id = -1,后端把 workspace_id IS NULL 塞这里)
  const { data: ungroupedTreeResp } = useQuery({
    queryKey: ["workspace-tree", -1],
    queryFn: () => getWorkspaceTree(-1),
    enabled: true,
  });

  // 3. 真实 workspace 的 tree(并行拉)
  const workspaceTreeQueries = useQuery({
    queryKey: ["workspace-trees", workspaces.map((w) => w.id).join(",")],
    queryFn: async () => {
      const map: Record<number, WorkspaceTreeResponse | null> = {
        [-1]: ungroupedTreeResp?.data ?? null,
      };
      await Promise.all(
        workspaces.map(async (w) => {
          const r = await getWorkspaceTree(w.id);
          map[w.id] = r.data ?? null;
        })
      );
      return map;
    },
    enabled: workspaces.length > 0,
  });

  // 拍平 → WorkspaceTree 期待的 Record<wsId, tree|null>
  const treesByWorkspace = useMemo<
    Record<number, WorkspaceTreeResponse | null>
  >(() => {
    if (workspaceTreeQueries.data) return workspaceTreeQueries.data;
    return { [-1]: ungroupedTreeResp?.data ?? null };
  }, [workspaceTreeQueries.data, ungroupedTreeResp?.data]);

  const workspaceTreeLoading = workspaceTreeQueries.isLoading;

  // 4. 当前 KB 的 folder 树(give to CreateFolderModal / MoveDocumentModal)
  const { data: folderTreeResp, refetch: refetchFolders } = useQuery({
    queryKey: ["folders-tree", selectedKB?.id],
    queryFn: () => listFolders(selectedKB!.id, { tree: true }),
    enabled: !!selectedKB,
  });
  const folderTree = (folderTreeResp?.data ?? []) as DocumentFolderTreeNode[];

  // ──────────── handlers ────────────
  // sidebar 点 workspace → 清 KB / folder / documents(由 page 通过 onKbChange 接)
  const handleSelectWorkspace = useCallback(
    (workspaceId: number | null) => {
      setSelectedWorkspaceId(workspaceId);
      setSelectedFolderId(null);
      onKbChange(null);
    },
    [onKbChange]
  );

  // sidebar 点 KB → fetch 详情后回调 page
  const handleSelectKb = useCallback(
    async (_workspaceId: number | null, kbId: number | null) => {
      if (kbId == null) {
        setSelectedFolderId(null);
        onKbChange(null);
        return;
      }
      try {
        const resp = await knowledgeApi.get(kbId);
        if (resp.data.code === 200 && resp.data.data) {
          setSelectedFolderId(null);
          onKbChange(resp.data.data);
        }
      } catch {
        message.error("加载知识库详情失败");
      }
    },
    [onKbChange]
  );

  // sidebar 点 folder → 同步 selectedKB(可能 sidebar 直接点 folder,KB 也要跟)+ set folderId
  const handleSelectFolder = useCallback(
    async (
      _workspaceId: number | null,
      kbId: number,
      folderId: number | null
    ) => {
      // 确保 selectedKB 同步
      if (!selectedKB || selectedKB.id !== kbId) {
        try {
          const resp = await knowledgeApi.get(kbId);
          if (resp.data.code === 200 && resp.data.data) {
            onKbChange(resp.data.data);
          }
        } catch {
          message.error("加载知识库详情失败");
          return;
        }
      }
      setSelectedFolderId(folderId);
    },
    [selectedKB, onKbChange]
  );

  // CreateWorkspaceModal 提交 → invalidate workspaces + workspace-trees
  const handleCreateWorkspace = useCallback(
    async (payload: {
      name: string;
      description?: string;
      icon?: string;
      color?: string;
    }) => {
      try {
        const resp = await createWorkspace(payload);
        if (resp.code === 200) {
          message.success("Workspace 已创建");
          setCreateWsOpen(false);
          queryClient.invalidateQueries({ queryKey: ["workspaces", "list"] });
          queryClient.invalidateQueries({ queryKey: ["workspace-trees"] });
        } else {
          message.error(resp.message || "创建失败");
        }
      } catch (error: any) {
        message.error(
          error?.response?.data?.detail || error?.message || "创建失败"
        );
      }
    },
    [queryClient]
  );

  // CreateFolderModal 提交 → invalidate folder tree + workspace-trees
  const handleCreateFolder = useCallback(
    async (payload: {
      name: string;
      parent_id?: number | null;
      description?: string;
      order_index?: number;
    }) => {
      if (!selectedKB) return;
      try {
        const resp = await createFolder(selectedKB.id, payload);
        if (resp.code === 200) {
          message.success("Folder 已创建");
          setCreateFolderOpen(false);
          refetchFolders();
          queryClient.invalidateQueries({ queryKey: ["workspace-trees"] });
        } else {
          message.error(resp.message || "创建失败");
        }
      } catch (error: any) {
        message.error(
          error?.response?.data?.detail || error?.message || "创建失败"
        );
      }
    },
    [selectedKB, refetchFolders, queryClient]
  );

  // MoveDocumentModal 提交 → 由 page 层接 refetch(fetchDocuments 是 useDocumentList 的)
  const handleMoveDocument = useCallback(
    async (payload: { target_folder_id: number | null }) => {
      if (!movingDoc) return;
      try {
        const resp = await moveDocument(movingDoc.id, payload);
        if (resp.moved) {
          message.success(
            payload.target_folder_id == null
              ? "已移到 KB 根目录"
              : "文档已移动"
          );
          setMoveDocOpen(false);
          setMovingDoc(null);
          refetchFolders();
          queryClient.invalidateQueries({ queryKey: ["workspace-trees"] });
        }
      } catch (error: any) {
        message.error(
          error?.response?.data?.detail || error?.message || "移动失败"
        );
      }
    },
    [movingDoc, refetchFolders, queryClient]
  );

  // 2.1 C.12: KB 跨 workspace 移动(drag-drop)
  const handleMoveKbDrag = useCallback(
    async (kbId: number, targetWorkspaceId: number | null) => {
      try {
        const resp = await knowledgeApi.update(kbId, {
          workspace_id: targetWorkspaceId,
        });
        if (resp.data.code === 200) {
          message.success(
            targetWorkspaceId == null
              ? "已移到未分组"
              : "知识库已切换 workspace"
          );
          queryClient.invalidateQueries({ queryKey: ["workspace-trees"] });
          queryClient.invalidateQueries({ queryKey: ["workspaces", "list"] });
        } else {
          message.error(resp.data.message || "移动失败");
        }
      } catch (error: any) {
        message.error(
          error?.response?.data?.detail || error?.message || "移动失败"
        );
      }
    },
    [queryClient]
  );

  // 2.1 C.12: folder 跨 parent 移动(drag-drop)
  const handleMoveFolderDrag = useCallback(
    async (
      folderId: number,
      targetParentId: number | null,
      _targetKbId: number | null
    ) => {
      try {
        const resp = await updateFolder(folderId, { parent_id: targetParentId });
        if (resp.code === 200) {
          message.success("Folder 已移动");
          refetchFolders();
          queryClient.invalidateQueries({ queryKey: ["workspace-trees"] });
        } else {
          message.error(resp.message || "移动失败");
        }
      } catch (error: any) {
        message.error(
          error?.response?.data?.detail || error?.message || "移动失败"
        );
      }
    },
    [refetchFolders, queryClient]
  );

  return {
    // selection
    selectedWorkspaceId,
    setSelectedWorkspaceId,
    selectedFolderId,
    setSelectedFolderId,
    currentUserId,
    // queries
    workspaces,
    treesByWorkspace,
    workspaceTreeLoading,
    folderTree,
    refetchFolders,
    // modal + moving doc
    createWsOpen,
    setCreateWsOpen,
    createFolderOpen,
    setCreateFolderOpen,
    moveDocOpen,
    setMoveDocOpen,
    movingDoc,
    setMovingDoc,
    membersOpen,
    setMembersOpen,
    // handlers
    handleSelectWorkspace,
    handleSelectKb,
    handleSelectFolder,
    handleCreateWorkspace,
    handleCreateFolder,
    handleMoveDocument,
    handleMoveKbDrag,
    handleMoveFolderDrag,
  };
}
