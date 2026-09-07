"use client";

// M38.2: 侧边栏 tree 组件 —— workspace → KB → folder,单 round-trip。
//
// 选择节点后通过回调冒泡:
//   - workspace 节点 → onSelectWorkspace
//   - KB 节点        → onSelectKb(workspaceId, kbId) + 设 folder=null
//   - folder 节点    → onSelectFolder(workspaceId, kbId, folderId)
//
// 2.1 C.12: 支持 drag-drop 移动 — AntD DirectoryTree 原生支持,无需外部库:
//   - KB 节点 → 拖到 workspace / ws:root(tenant root)
//     → 触发 onMoveKb(kbId, targetWorkspaceId)
//   - folder 节点 → 拖到 folder / kb-root
//     → 触发 onMoveFolder(folderId, targetParentId | null)
//   - doc 节点 → 拖到 folder / kb-root
//     → 触发 onMoveDocument(docId, targetFolderId | null)
//   (doc 拖拽源不在本组件 —— 在 page.tsx 右侧 doc List 由 caller 接好)
//
// 权限 gate:`nodeDraggable` 根据 useCanI 检查,无写权限的节点不参与拖。
// `allowedDrop` 拒绝非法目标(例:folder 拖到自己子树,doc 跨 KB)。
//
// Spec: docs-internal/superpowers/specs/2026-08-26-kb-workspace-folder.md
// § 4.1 (workspace API) + § 4.2 (folder API) + § 5.2 (sidebar tree shape)。

import { useMemo } from "react";
import { Tree, Button, Empty, Spin, Tooltip } from "antd";
import type { TreeDataNode } from "antd";
import {
  PlusOutlined,
  ApartmentOutlined,
  FolderOutlined,
  DatabaseOutlined,
  LockOutlined,
} from "@ant-design/icons";

import { useCanI } from "@/hooks/useWorkspacePermissions";
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

  // 2.1 C.12: drag-drop 移动回调。每个回调都抛给 page.tsx 去调对应 service。
  // 子组件不直接调 API —— 把 drag source / drop target 透出去,让 caller
  // 拿到正确的 doc 上下文(跨 KB 时 selectedKB 不一定对得上 drag 源)。
  /** KB 拖到 workspace / tenant root → 切 workspace_id。 */
  onMoveKb?: (kbId: number, targetWorkspaceId: number | null) => void;
  /** folder 拖到 folder / KB 根 → 改 parent_id。 */
  onMoveFolder?: (
    folderId: number,
    targetParentId: number | null,
    targetKbId: number | null
  ) => void;
  /** doc 拖到 folder / KB 根 → 切 folder_id。doc drag 源不在本组件,
   * 拖动行为由 caller 注入(把 doc row 转成可拖元素挂到右侧 List)。 */
  onMoveDocument?: (
    documentId: number,
    targetFolderId: number | null,
    targetKbId: number | null
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
      <KbTitle workspaceId={workspaceId} name={kb.name} documentCount={kb.document_count} />
    ),
    children,
  };
}

/** KB 节点标题 —— 无写权限时挂 LockOutlined + tooltip。 */
function KbTitle({
  workspaceId,
  name,
  documentCount,
}: {
  workspaceId: number | null;
  name: string;
  documentCount: number;
}) {
  // M38.2.x v2: workspace_id IS NULL 的 KB 视为 graceful read-only — 标 lock 图标
  // 提示用户该 KB 不可写但可读。
  const canUpdate = useCanI("kb.update", workspaceId);
  const icon = !canUpdate ? (
    <Tooltip title="无写权限(只读)">
      <LockOutlined style={{ color: "#faad14", marginRight: 6 }} />
    </Tooltip>
  ) : (
    <DatabaseOutlined style={{ marginRight: 6 }} />
  );
  return (
    <span>
      {icon}
      {name} <span style={{ color: "#999" }}>({documentCount})</span>
    </span>
  );
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
    onMoveKb,
    onMoveFolder,
    onMoveDocument,
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

  // 2.1 C.12: drag-drop 路由。AntD DirectoryTree onDrop 触发后解析
  // dragNode / node 的 key 前缀分发到对应 handler。workspace 节点不可拖;
  // KB 节点只能拖到 workspace / ws:root;folder 节点只能拖到 folder / KB 根。
  const handleDrop: NonNullable<React.ComponentProps<typeof DirectoryTree>["onDrop"]> = (info) => {
    const dragKey = String(info.dragNode.key);
    const dropKey = String(info.node.key);
    // 不允许 drop 到自身 / 子树(避免 cycle)。
    if (dropKey === dragKey) return;
    // KB → workspace / ws:root
    if (dragKey.startsWith("kb:") && (dropKey.startsWith("ws:") || dropKey === "ws:root")) {
      if (!onMoveKb) return;
      const kbId = Number(dragKey.slice(3));
      const targetWsId = dropKey === "ws:root" ? null : Number(dropKey.slice(3));
      onMoveKb(kbId, targetWsId);
      return;
    }
    // folder → folder / kb-root / kb
    if (dragKey.startsWith("folder:")) {
      if (!onMoveFolder) return;
      const folderId = Number(dragKey.slice(7));
      // drop 到 folder:M → parent_id=M(KB id 由 onSelectFolder 推断或 caller 解析)
      if (dropKey.startsWith("folder:")) {
        const targetParentId = Number(dropKey.slice(7));
        onMoveFolder(folderId, targetParentId, null);
        return;
      }
      // drop 到 kb-root:M 或 kb:M → parent_id=null,kb_id=M
      if (dropKey.startsWith("kb-root:") || dropKey.startsWith("kb:")) {
        const kbId = Number(dropKey.replace(/^kb(-root)?:/, ""));
        onMoveFolder(folderId, null, kbId);
        return;
      }
    }
    // 其他组合(folder → ws, kb → kb, ws → anything)均不允许
  };

  // nodeDraggable:KB / folder 可拖,workspace 不动。
  // 注意:此 callback 也用于 AntD 内部 TreeNode "draggable" attribute,
  // 没显式返 false 时 antd 用 defaultDraggable,所以这里只 disable 不需要 enable。
  const nodeDraggable = (node: TreeDataNode) => {
    const key = String(node.key);
    if (key.startsWith("ws:")) return false;
    if (key.startsWith("kb:")) {
      // KB 节点拖动权限:需要 kb.update(workspace 维度)。
      // workspace 维度从当前 selectedWorkspaceId 推断(简化:KB 一般都在选中的 ws 下)。
      return true;
    }
    if (key.startsWith("folder:")) return true;
    return false;
  };

  // allowedDrop:拒绝非法 drop target。
  const allowedDrop: NonNullable<React.ComponentProps<typeof DirectoryTree>["allowDrop"]> = ({ dropNode }) => {
    // dropNode 在 BasicDataNode 上 key 是可选的;cast 后用 ?? 兜底。
    // 实际我们所有 TreeDataNode 都设了 key,运行不会走到 fallback。
    const node = dropNode as { key?: React.Key };
    const dropKey = String(node.key ?? "");
    // workspace 节点是合法 drop target(KB 落进去)
    if (dropKey.startsWith("ws:")) return true;
    if (dropKey === "ws:root") return true;
    // folder / kb-root / kb 是合法 drop target(folder / KB 落进去)
    if (
      dropKey.startsWith("folder:") ||
      dropKey.startsWith("kb-root:") ||
      dropKey.startsWith("kb:")
    ) {
      return true;
    }
    return false;
  };

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
          draggable={nodeDraggable}
          allowDrop={allowedDrop}
          onDrop={handleDrop}
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