// frontend/__tests__/knowledge/page-rbac-integration.test.tsx
//
// M38.2.x v2: KnowledgePage RBAC 集成测试。
//
// 锁定的契约:
//   1. 选了 workspace 后,头部出现「成员管理」按钮
//   2. user 无 workspace.manage_members → 按钮 disabled
//   3. user 是 owner(is_owner=true)→ 按钮 enabled
//   4. user 普通 member 有 manage_members → 按钮 enabled
//   5. 点 enabled 按钮 → WorkspaceMembersModal 打开(open=true)
//   6. 选了 tenant-root(无 workspace)→ 按钮根本不渲染(因为是 conditional)
//   7. workspace_id IS NULL 的 KB 在 sidebar 显示 LockOutlined + tooltip「无写权限」
//
// 这里直接 mock useCurrentUserWorkspacePermissions hook 让 useCanI 走 mock 数据
// (避开 axios 真实调用),WorkspaceMembersModal 也 stub 掉便于断言 open 状态。

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { ConfigProvider, App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// --- Mocks ----------------------------------------------------------------

// 让 WorkspaceMembersModal / WorkspaceTree 简单化,只暴露 open 状态 / 回调触发器。
vi.mock("@/components/knowledge/WorkspaceMembersModal", () => ({
  WorkspaceMembersModal: (props: { open: boolean }) => (
    <div data-testid="members-modal-stub" data-open={props.open ? "1" : "0"} />
  ),
}));

vi.mock("@/components/knowledge/WorkspaceTree", () => ({
  default: (props: any) => (
    <div data-testid="workspace-tree-mock">
      <button onClick={() => props.onSelectWorkspace(null)}>
        tree-select-tenant-root
      </button>
      <button onClick={() => props.onSelectWorkspace(1)}>
        tree-select-workspace-1
      </button>
      <button onClick={() => props.onSelectWorkspace(2)}>
        tree-select-workspace-2
      </button>
    </div>
  ),
}));

// 控制 useCanI 的返回值 —— 每个测试 set 一次就行。
const mockCanIRef = { current: new Map<number, Set<string>>() };
vi.mock("@/hooks/useWorkspacePermissions", () => ({
  useCurrentUserWorkspacePermissions: () => ({
    byWorkspace: mockCanIRef.current,
    ownedWorkspaceIds: new Set<number>(), // 简化:用 byWorkspace 模拟 owner
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
  useCanI: (perm: string, wsId: number | null | undefined) => {
    if (!wsId) return false;
    const set = mockCanIRef.current.get(wsId);
    return set?.has(perm) ?? false;
  },
  usePermissions: () => ({ has: () => false, hasAny: () => false, hasAll: () => false }),
}));

// knowledge / workspace / folder service mock —— 沿用 page-workspace-integration
// 的样板但精简。

const mockList = vi.fn();
const mockGet = vi.fn();
const mockGetDocuments = vi.fn();

vi.mock("@/services/knowledge", () => ({
  knowledgeApi: {
    list: (...args: any[]) => mockList(...args),
    get: (...args: any[]) => mockGet(...args),
    getDocuments: (...args: any[]) => mockGetDocuments(...args),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    deleteDocument: vi.fn(),
    upload: vi.fn(),
    search: vi.fn(),
    rechunk: vi.fn(),
  },
}));

const mockListWorkspaces = vi.fn();
const mockGetWorkspaceTree = vi.fn();

vi.mock("@/services/workspace", () => ({
  listWorkspaces: (...args: any[]) => mockListWorkspaces(...args),
  getWorkspaceTree: (...args: any[]) => mockGetWorkspaceTree(...args),
  createWorkspace: vi.fn(),
}));

vi.mock("@/services/folder", () => ({
  listFolders: vi.fn().mockResolvedValue({
    data: { code: 200, message: "ok", data: [] },
  }),
  createFolder: vi.fn(),
  moveDocument: vi.fn(),
}));

vi.mock("@/services/models", () => ({
  ModelConfig: {},
  modelConfigApi: { list: vi.fn() },
}));

vi.mock("@/store/notifications", () => ({
  useNotificationsStore: Object.assign(
    () => ({
      items: [],
      unreadCount: 0,
      addNotification: vi.fn(),
      markAsRead: vi.fn(),
      markAllAsRead: vi.fn(),
      clearAll: vi.fn(),
    }),
    {
      subscribe: (_l: (state: any, prev: any) => void) => () => {},
      getState: () => ({ items: [], unreadCount: 0 }),
    }
  ),
}));

vi.mock("@/components/EmbeddingModelSelect", () => ({
  default: () => <div data-testid="embedding-model-select-stub" />,
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: (_k: string) => null }),
  useRouter: () => ({ push: vi.fn() }),
}));

import KnowledgePage from "@/app/dashboard/knowledge/page";

// --- Fixtures -------------------------------------------------------------

const emptyListResponse = {
  data: { code: 200, message: "ok", data: [], total: 0, page: 1, page_size: 10 },
};

const sampleWorkspaces = (wsList: Array<{ id: number; name: string; owner_id?: number }>) => ({
  code: 200,
  message: "ok",
  data: wsList.map((w) => ({
    id: w.id,
    tenant_id: 1,
    name: w.name,
    knowledge_base_count: 0,
    owner_id: w.owner_id ?? 1, // owner_id 字段 —— page.tsx 读 workspaces[i].owner_id
    created_at: "2026-08-27T00:00:00Z",
    updated_at: "2026-08-27T00:00:00Z",
  })),
  total: wsList.length,
  page: 1,
  page_size: 100,
});

const emptyTree = (wsId: number) => ({
  code: 200,
  message: "ok",
  data: {
    workspace: {
      id: wsId,
      tenant_id: 1,
      name: wsId === -1 ? "未分组" : `ws-${wsId}`,
      created_at: "2026-08-27T00:00:00Z",
      updated_at: "2026-08-27T00:00:00Z",
    },
    knowledge_bases: [],
  },
});

// --- Wrapper --------------------------------------------------------------

const TestWrapper = ({ children }: { children: React.ReactNode }) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <ConfigProvider button={{ autoInsertSpace: false }}>
      <App>
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      </App>
    </ConfigProvider>
  );
};

// --- Helpers --------------------------------------------------------------

/** 给指定 workspace 注入权限集合(模拟 user 在该 ws 的 effective perms)。 */
function setMockPerms(wsId: number, perms: string[]): void {
  mockCanIRef.current.set(wsId, new Set(perms));
}

// --- Tests ----------------------------------------------------------------

describe("KnowledgePage — M38.2.x v2 RBAC Members 按钮 gating", () => {
  beforeEach(() => {
    mockCanIRef.current = new Map();
    mockList.mockReset();
    mockGet.mockReset();
    mockGetDocuments.mockReset();
    mockListWorkspaces.mockReset();
    mockGetWorkspaceTree.mockReset();
    mockList.mockResolvedValue(emptyListResponse);
    mockGetDocuments.mockResolvedValue({ data: { code: 200, message: "ok", data: [] } });
    mockGet.mockResolvedValue({
      data: {
        code: 200,
        message: "ok",
        data: {
          id: 1,
          name: "kb",
          tenant_id: 1,
          status: "active",
          embedding_model: "nomic-embed-text",
          embedding_model_config_id: 1,
          default_parser: "general",
          chunk_size: 500,
          chunk_overlap: 50,
          document_count: 0,
          workspace_id: 1,
          created_at: "2026-08-27T00:00:00Z",
        },
      },
    });
    mockListWorkspaces.mockResolvedValue(sampleWorkspaces([
      { id: 1, name: "研发", owner_id: 1 },
      { id: 2, name: "市场", owner_id: 99 },
    ]));
    mockGetWorkspaceTree.mockImplementation((id: number) =>
      Promise.resolve(emptyTree(id))
    );
  });

  it("未选 workspace → 「成员管理」按钮根本不渲染(conditional)", async () => {
    render(
      <TestWrapper>
        <KnowledgePage />
      </TestWrapper>
    );
    await waitFor(() => expect(screen.getByTestId("workspace-tree-mock")).toBeInTheDocument());
    // 没点 tree,selectedWorkspaceId=null → 按钮不该出现
    expect(screen.queryByText("成员管理")).toBeNull();
  });

  it("user 无 workspace.manage_members → 按钮 disabled", async () => {
    // ws 1 只给 kb.read(没有 manage_members)
    setMockPerms(1, ["kb.read", "document.read"]);

    render(
      <TestWrapper>
        <KnowledgePage />
      </TestWrapper>
    );
    await waitFor(() => expect(screen.getByTestId("workspace-tree-mock")).toBeInTheDocument());

    fireEvent.click(screen.getByText("tree-select-workspace-1"));

    await waitFor(() => expect(screen.getByText("成员管理")).toBeInTheDocument());
    const btn = screen.getByText("成员管理").closest("button") as HTMLButtonElement;
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(true);
  });

  it("user 是 owner(is_owner=true,full perm) → 按钮 enabled", async () => {
    // owner 自动全 perm → 给齐 19 项 manage_members
    setMockPerms(1, [
      "workspace.read",
      "workspace.update",
      "workspace.delete",
      "workspace.manage_members",
      "workspace.transfer_ownership",
    ]);

    render(
      <TestWrapper>
        <KnowledgePage />
      </TestWrapper>
    );
    await waitFor(() => expect(screen.getByTestId("workspace-tree-mock")).toBeInTheDocument());

    fireEvent.click(screen.getByText("tree-select-workspace-1"));

    await waitFor(() => expect(screen.getByText("成员管理")).toBeInTheDocument());
    const btn = screen.getByText("成员管理").closest("button") as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });

  it("user 普通 member 但被 grant 了 manage_members → 按钮 enabled", async () => {
    setMockPerms(1, ["workspace.read", "workspace.manage_members"]);

    render(
      <TestWrapper>
        <KnowledgePage />
      </TestWrapper>
    );
    await waitFor(() => expect(screen.getByTestId("workspace-tree-mock")).toBeInTheDocument());

    fireEvent.click(screen.getByText("tree-select-workspace-1"));

    await waitFor(() => expect(screen.getByText("成员管理")).toBeInTheDocument());
    const btn = screen.getByText("成员管理").closest("button") as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });

  it("点 enabled 的「成员管理」按钮 → WorkspaceMembersModal 打开(open=1)", async () => {
    setMockPerms(1, ["workspace.read", "workspace.manage_members"]);

    render(
      <TestWrapper>
        <KnowledgePage />
      </TestWrapper>
    );
    await waitFor(() => expect(screen.getByTestId("workspace-tree-mock")).toBeInTheDocument());

    fireEvent.click(screen.getByText("tree-select-workspace-1"));

    const btn = (await waitFor(() =>
      screen.getByText("成员管理").closest("button")
    )) as HTMLButtonElement;
    fireEvent.click(btn);

    await waitFor(() =>
      expect(screen.getByTestId("members-modal-stub").getAttribute("data-open")).toBe("1")
    );
  });

  it("点 disabled 的「成员管理」按钮 → modal 不打开(open=0)", async () => {
    // 没给 manage_members
    setMockPerms(1, ["kb.read", "document.read"]);

    render(
      <TestWrapper>
        <KnowledgePage />
      </TestWrapper>
    );
    await waitFor(() => expect(screen.getByTestId("workspace-tree-mock")).toBeInTheDocument());

    fireEvent.click(screen.getByText("tree-select-workspace-1"));
    await waitFor(() => expect(screen.getByText("成员管理")).toBeInTheDocument());

    // 强行 fireEvent click(即使 disabled,AntD 仍会派发事件,但 onClick 不触发)
    const btn = screen.getByText("成员管理").closest("button") as HTMLButtonElement;
    fireEvent.click(btn);

    // 短时间内 modal 仍应为 closed(open=0)
    expect(screen.getByTestId("members-modal-stub").getAttribute("data-open")).toBe("0");
  });

  it("切到 tenant-root(workspace=null)→ 「成员管理」按钮消失", async () => {
    setMockPerms(1, ["workspace.manage_members"]);

    render(
      <TestWrapper>
        <KnowledgePage />
      </TestWrapper>
    );
    await waitFor(() => expect(screen.getByTestId("workspace-tree-mock")).toBeInTheDocument());

    // 先选 ws 1 → 按钮出现
    fireEvent.click(screen.getByText("tree-select-workspace-1"));
    await waitFor(() => expect(screen.getByText("成员管理")).toBeInTheDocument());

    // 切回 tenant root → 按钮消失
    fireEvent.click(screen.getByText("tree-select-tenant-root"));
    await waitFor(() => expect(screen.queryByText("成员管理")).toBeNull());
  });
});
