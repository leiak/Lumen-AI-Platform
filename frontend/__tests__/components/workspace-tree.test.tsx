// M38.2: WorkspaceTree sidebar — 验证 onSelectWorkspace / onSelectKb /
// onSelectFolder 三组回调在不同节点 key 上的冒泡路径。
//
// 不验证 tree 的视觉(AntD DirectoryTree 内部已经测过),
// 只保证节点 key → 回调的映射正确:
  //   ws:root        → onSelectWorkspace(null) + onSelectKb(null, null)
  //   ws:N           → onSelectWorkspace(N) + onSelectKb(N, null)
  //   kb:N           → onSelectKb(ws, N)
  //   kb-root:N      → onSelectFolder(ws, N, null) + onSelectKb(ws, N)
  //   folder:N       → onSelectFolder(ws, kbId, N)
  //
// 这层契约一旦错,sidebar 整个交互链断,所以做组件级单测兜底。

import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ConfigProvider, App } from "antd";
import WorkspaceTree, {
  workspaceTreeKeyOf,
} from "@/components/knowledge/WorkspaceTree";
import type { WorkspaceTreeResponse } from "@/types/workspace";

const sampleWsTree = (): WorkspaceTreeResponse => ({
  workspace: {
    id: 1,
    tenant_id: 1,
    name: "研发",
    knowledge_base_count: 1,
    created_at: "2026-08-26T00:00:00Z",
    updated_at: "2026-08-26T00:00:00Z",
  },
  knowledge_bases: [
    {
      id: 100,
      name: "API 规范",
      document_count: 12,
      folders: [
        {
          id: 200,
          name: "v1",
          document_count: 5,
          children: [
            {
              id: 201,
              name: "auth",
              document_count: 2,
              children: [],
            },
          ],
        },
      ],
    },
  ],
});

const sampleUngrouped = (): WorkspaceTreeResponse => ({
  workspace: {
    id: -1,
    tenant_id: 1,
    name: "未分组",
    knowledge_base_count: 1,
    created_at: "2026-08-26T00:00:00Z",
    updated_at: "2026-08-26T00:00:00Z",
  },
  knowledge_bases: [
    {
      id: 999,
      name: "legacy KB",
      document_count: 1,
      folders: [],
    },
  ],
});

describe("WorkspaceTree — selection callback routing", () => {
  it("点击未分组根节点 → onSelectWorkspace(null) + onSelectKb(null, null)", () => {
    const onSelectWorkspace = vi.fn();
    const onSelectKb = vi.fn();
    const onSelectFolder = vi.fn();
    const onCreateWorkspace = vi.fn();
    const onCreateFolder = vi.fn();

    render(
      <ConfigProvider>
        <App>
          <WorkspaceTree
            selectedWorkspaceId={null}
            selectedKbId={null}
            selectedFolderId={null}
            treesByWorkspace={{ [-1]: sampleUngrouped() }}
            loading={false}
            onCreateWorkspace={onCreateWorkspace}
            onCreateFolder={onCreateFolder}
            onSelectWorkspace={onSelectWorkspace}
            onSelectKb={onSelectKb}
            onSelectFolder={onSelectFolder}
          />
        </App>
      </ConfigProvider>
    );

    fireEvent.click(screen.getByText("未分组"));
    expect(onSelectWorkspace).toHaveBeenCalledWith(null);
    expect(onSelectKb).toHaveBeenCalledWith(null, null);
    expect(onSelectFolder).not.toHaveBeenCalled();
  });

  it("点击 workspace 节点 → onSelectWorkspace(id) + onSelectKb(id, null)", () => {
    const onSelectWorkspace = vi.fn();
    const onSelectKb = vi.fn();
    const onSelectFolder = vi.fn();

    render(
      <ConfigProvider>
        <App>
          <WorkspaceTree
            selectedWorkspaceId={null}
            selectedKbId={null}
            selectedFolderId={null}
            treesByWorkspace={{ [-1]: null, 1: sampleWsTree() }}
            loading={false}
            onCreateWorkspace={vi.fn()}
            onCreateFolder={vi.fn()}
            onSelectWorkspace={onSelectWorkspace}
            onSelectKb={onSelectKb}
            onSelectFolder={onSelectFolder}
          />
        </App>
      </ConfigProvider>
    );

    fireEvent.click(screen.getByText("研发"));
    expect(onSelectWorkspace).toHaveBeenCalledWith(1);
    expect(onSelectKb).toHaveBeenCalledWith(1, null);
    expect(onSelectFolder).not.toHaveBeenCalled();
  });

  // KB / kb-root / folder 的回调路由不在这里测:
  // AntD DirectoryTree 在 title 点击时 toggle 展开,点了 KB 之后
  // folder 节点会从 DOM 消失,getByText("v1") 直接抛错。
  // 这层路由在 __tests__/knowledge/page-workspace-integration.test.tsx
  // 用 MockTree 端到端覆盖。

  // (见上:不再在此测 kb / folder 路由。)

  // (见上:不再在此测 folder 路由。)

  it("顶层「新建 workspace」按钮 → onCreateWorkspace", () => {
    const onCreateWorkspace = vi.fn();

    render(
      <ConfigProvider>
        <App>
          <WorkspaceTree
            selectedWorkspaceId={null}
            selectedKbId={null}
            selectedFolderId={null}
            treesByWorkspace={{}}
            loading={false}
            onCreateWorkspace={onCreateWorkspace}
            onCreateFolder={vi.fn()}
            onSelectWorkspace={vi.fn()}
            onSelectKb={vi.fn()}
            onSelectFolder={vi.fn()}
          />
        </App>
      </ConfigProvider>
    );

    fireEvent.click(screen.getByTitle("新建 workspace"));
    expect(onCreateWorkspace).toHaveBeenCalledOnce();
  });

  it("无 workspace / KB 时显示 Empty 占位", () => {
    render(
      <ConfigProvider>
        <App>
          <WorkspaceTree
            selectedWorkspaceId={null}
            selectedKbId={null}
            selectedFolderId={null}
            treesByWorkspace={{ [-1]: null }}
            loading={false}
            onCreateWorkspace={vi.fn()}
            onCreateFolder={vi.fn()}
            onSelectWorkspace={vi.fn()}
            onSelectKb={vi.fn()}
            onSelectFolder={vi.fn()}
          />
        </App>
      </ConfigProvider>
    );

    expect(screen.getByText(/还没有 workspace/)).toBeTruthy();
  });
});

describe("workspaceTreeKeyOf — selectedKey 反推 helper", () => {
  it("folder 优先于 kb / workspace", () => {
    expect(workspaceTreeKeyOf(1, 100, 200)).toBe("folder:200");
  });
  it("无 folder 时取 kb", () => {
    expect(workspaceTreeKeyOf(1, 100, null)).toBe("kb:100");
  });
  it("无 kb 时取 workspace", () => {
    expect(workspaceTreeKeyOf(1, null, null)).toBe("ws:1");
  });
  it("全 null 时返回 ws:root", () => {
    expect(workspaceTreeKeyOf(null, null, null)).toBe("ws:root");
  });
});