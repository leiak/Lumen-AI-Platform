"use client";

// M38.2: 侧边栏 tree 组件 —— workspace → KB → folder,单 round-trip。
//
// 选择节点后通过回调冒泡:
//   - workspace 节点 → onSelectWorkspace
//   - KB 节点        → onSelectKb(workspaceId, kbId) + 设 folder=null
//   - folder 节点    → onSelectFolder(workspaceId, kbId, folderId)
//
// Spec: docs-internal/superpowers/specs/2026-08-26-kb-workspace-folder.md
// § 4.1 (workspace API) + § 4.2 (folder API) + § 5.2 (sidebar tree shape).

import { useMemo } from "react";
import { Tree, Button, Empty, Spin } from "antd";
import type { TreeDataNode } from "antd";
import {
  PlusOutlined,
  ApartmentOutlined,
  FolderOutlined,
  DatabaseOutlined,
} from "@ant-design/icons";

import type {
  KnowledgeBaseTreeNode,
  WorkspaceTreeResponse,
} from "@/types/workspace";

const { DirectoryTree } = Tree;

export interface WorkspaceTreeProps {
  /** Currently active workspace (or null = "tenant root"). */
  selectedWorkspaceId: number | null;
  /** Currently active KB (or null = "all KBs in workspace"). */
  selectedKbId: number | null;
  /** Currently active folder (or null = "KB root"). */
  selectedFolderId: number | null;

  /** Trees grouped by workspace id (or -1 for the implicit "tenant root"
   * bucket where workspace_id IS NULL). */
  treesByWorkspace: Record<number, WorkspaceTreeResponse | null>;

  /** Loading state. */
  loading: boolean;

  /** Action buttons. */
  onCreateWorkspace: () => void;
  onCreateFolder: (workspaceId: number, kbId: number) => void;

  onSelectWorkspace: (workspaceId: number | null) => void;
  onSelectKb: (workspaceId: number | null, kbId: number | null) => void;
  onSelectFolder: (
    workspaceId: number | null,
    kbId: number,
    folderId: number | null
  ) => void;

  /**
   * Whether to expand all nodes by default. Default ``false`` (collapsed,
   * 用户从 workspace 节点点开 → KB → folder,层层递进)。
   * 测试场景可设为 ``true`` 让节点默认可见便于点击。
   */
  defaultExpandAll?: boolean;
}

function kbNode(
  workspaceId: number | null,
  kb: KnowledgeBaseTreeNode
): TreeDataNode {
  const children: TreeDataNode[] = kb.folders.map((f) =>
    folderNode(workspaceId, kb.id, f)
  );
  // +「KB 根」虚节点让用户能切回 folder_id=0 (KB root)。
  children.unshift({
    key: `kb-root:${kb.id}`,
    title: (
      <span>
        <FolderOutlined /> 根目录{" "}
        <span style={{ color: "#999" }}>({kb.document_count})</span>
      </span>
    ),
    isLeaf: true,
  });
  return {
    key: `kb:${kb.id}`,
    title: (
      <span>
        <DatabaseOutlined /> {kb.name}{" "}
        <span style={{ color: "#999" }}>({kb.document_count})</span>
      </span>
    ),
    children,
  };
}

function folderNode(
  workspaceId: number | null,
  kbId: number,
  folder: { id: number; name: string; document_count: number; children: any[] }
): TreeDataNode {
  return {
    key: `folder:${folder.id}`,
    title: (
      <span>
        <FolderOutlined /> {folder.name}{" "}
        <span style={{ color: "#999" }}>({folder.document_count})</span>
      </span>
    ),
    children: folder.children?.length
      ? folder.children.map((c) => folderNode(workspaceId, kbId, c))
      : undefined,
    isLeaf: !folder.children?.length,
  };
}

function workspaceNode(tree: WorkspaceTreeResponse): TreeDataNode {
  return {
    key: `ws:${tree.workspace.id}`,
    title: (
      <span>
        <ApartmentOutlined /> {tree.workspace.name}{" "}
        <span style={{ color: "#999" }}>
          ({tree.knowledge_bases.length} KB)
        </span>
      </span>
    ),
    children: tree.knowledge_bases.map((kb) =>
      kbNode(tree.workspace.id, kb)
    ),
  };
}

export default function WorkspaceTree(props: WorkspaceTreeProps) {
  const {
    selectedWorkspaceId,
    selectedKbId,
    selectedFolderId,
    treesByWorkspace,
    loading,
    onCreateWorkspace,
    onCreateFolder,
    onSelectWorkspace,
    onSelectKb,
    onSelectFolder,
    defaultExpandAll = false,
  } = props;

  const treeData: TreeDataNode[] = useMemo(() => {
    const data: TreeDataNode[] = [];
    // 「租户根」节点 —— workspace_id IS NULL 的 KB 挂在下面。
    data.push({
      key: "ws:root",
      title: (
        <span>
          <ApartmentOutlined /> 未分组
        </span>
      ),
      children: (treesByWorkspace[-1]?.knowledge_bases ?? []).map((kb) =>
        kbNode(null, kb)
      ),
    });
    Object.entries(treesByWorkspace).forEach(([key, tree]) => {
      if (key === "-1" || !tree) return;
      data.push(workspaceNode(tree));
    });
    return data;
  }, [treesByWorkspace]);

  // 当前选中的 key
  const selectedTreeKey = useMemo(() => {
    if (selectedFolderId != null) return `folder:${selectedFolderId}`;
    if (selectedKbId != null) return `kb:${selectedKbId}`;
    if (selectedWorkspaceId != null) return `ws:${selectedWorkspaceId}`;
    return "ws:root";
  }, [selectedWorkspaceId, selectedKbId, selectedFolderId]);

  if (loading && Object.keys(treesByWorkspace).length === 0) {
    return (
      <div style={{ padding: 16, textAlign: "center" }}>
        <Spin />
      </div>
    );
  }

  return (
    <div style={{ width: 240, padding: "8px 0" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "0 8px 8px",
          borderBottom: "1px solid #f0f0f0",
          marginBottom: 8,
        }}
      >
        <span style={{ fontWeight: 500 }}>导航</span>
        <Button
          type="text"
          size="small"
          icon={<PlusOutlined />}
          onClick={onCreateWorkspace}
          title="新建 workspace"
        />
      </div>
      {treeData.every((n) => !n.children?.length) ? (
        <Empty
          description="还没有 workspace,点击 + 创建"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          style={{ marginTop: 24 }}
        />
      ) : (
        <DirectoryTree
          treeData={treeData}
          defaultExpandAll={defaultExpandAll}
          selectedKeys={[selectedTreeKey]}
          onSelect={(_keys, info) => {
            const key = String(info.node.key);
            if (key === "ws:root") {
              onSelectWorkspace(null);
              onSelectKb(null, null);
              return;
            }
            if (key.startsWith("ws:")) {
              const id = Number(key.slice(3));
              onSelectWorkspace(id);
              onSelectKb(id, null);
              return;
            }
            if (key.startsWith("kb:")) {
              const id = Number(key.slice(3));
              // 通过当前选中的 workspace 推断
              const ws = selectedWorkspaceId;
              onSelectKb(ws, id);
              return;
            }
            if (key.startsWith("kb-root:")) {
              const id = Number(key.slice(8));
              onSelectFolder(selectedWorkspaceId, id, null);
              onSelectKb(selectedWorkspaceId, id);
              return;
            }
            if (key.startsWith("folder:")) {
              const folderId = Number(key.slice(7));
              if (selectedKbId != null) {
                onSelectFolder(selectedWorkspaceId, selectedKbId, folderId);
              }
              return;
            }
          }}
        />
      )}
    </div>
  );
}

/** 把 tree → 选择状态变化的 helper,供父组件用。 */
export function workspaceTreeKeyOf(
  workspaceId: number | null,
  kbId: number | null,
  folderId: number | null
): string {
  if (folderId != null) return `folder:${folderId}`;
  if (kbId != null) return `kb:${kbId}`;
  if (workspaceId != null) return `ws:${workspaceId}`;
  return "ws:root";
}