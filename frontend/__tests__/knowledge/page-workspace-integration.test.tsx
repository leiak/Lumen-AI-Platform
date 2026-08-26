// M38.2: KnowledgePage + workspace/folder sidebar 端到端 wiring 测试。
//
// 这层只验证页面把 sidebar 回调串到了正确的 service API 调用。
// 直接 mock WorkspaceTree 渲染一组简单的按钮触发回调 —— AntD DirectoryTree
// 在 jsdom 下 DOM 太复杂,直接 click 文本节点的链路有太多副作用。
//
// 覆盖:
//  1. 挂载后 sidebar 拉了 workspaces list + workspace tree API
//  2. MockTree 触发 onSelectKb → knowledgeApi.get(kbId) + fetchDocuments
//  3. MockTree 触发 onSelectFolder → knowledgeApi.getDocuments(kbId, folderId)
//  4. MockTree 触发 onCreateWorkspace → CreateWorkspaceModal 打开
//  5. MockTree 触发 onCreateFolder(KB 选中后) → CreateFolderModal 打开
//  6. 文档行「移动」按钮 → MoveDocumentModal 打开
//  7. 提交移动 → moveDocument(docId, payload),target_folder_id 反映当前 folder

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { ConfigProvider, App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Mock WorkspaceTree 渲染一组调用回调的 button —— 跳过 AntD DirectoryTree 的
// jsdom 渲染复杂性。
vi.mock("@/components/knowledge/WorkspaceTree", () => ({
  default: (props: any) => (
    <div data-testid="workspace-tree-mock">
      <button onClick={() => props.onSelectWorkspace(null)}>
        tree-select-tenant-root
      </button>
      <button onClick={() => props.onSelectWorkspace(1)}>
        tree-select-workspace-1
      </button>
      <button onClick={() => props.onSelectKb(1, 42)}>
        tree-select-kb-42
      </button>
      <button onClick={() => props.onSelectKb(null, 42)}>
        tree-select-kb-42-root
      </button>
      <button onClick={() => props.onSelectFolder(1, 42, 200)}>
        tree-select-folder-200
      </button>
      <button onClick={() => props.onSelectFolder(null, 42, null)}>
        tree-select-kb-root
      </button>
      <button onClick={() => props.onCreateWorkspace()}>
        tree-new-workspace
      </button>
      <button onClick={() => props.onCreateFolder(1, 42)}>
        tree-new-folder
      </button>
    </div>
  ),
}));

// 现在可以 import KnowledgePage(M38.2 引入 WorkspaceTree 会被上面的 mock 替换)
import KnowledgePage from "@/app/dashboard/knowledge/page";

// ─── Mocks ──────────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: (_k: string) => null }),
  useRouter: () => ({ push: vi.fn() }),
}));

const mockList = vi.fn();
const mockGet = vi.fn();
const mockGetDocuments = vi.fn();
const mockCreate = vi.fn();
const mockUpdate = vi.fn();
const mockDelete = vi.fn();
const mockDeleteDocument = vi.fn();
const mockUpload = vi.fn();
const mockSearch = vi.fn();
const mockRechunk = vi.fn();

vi.mock("@/services/knowledge", () => ({
  knowledgeApi: {
    list: (...args: any[]) => mockList(...args),
    get: (...args: any[]) => mockGet(...args),
    getDocuments: (...args: any[]) => mockGetDocuments(...args),
    create: (...args: any[]) => mockCreate(...args),
    update: (...args: any[]) => mockUpdate(...args),
    delete: (...args: any[]) => mockDelete(...args),
    deleteDocument: (...args: any[]) => mockDeleteDocument(...args),
    upload: (...args: any[]) => mockUpload(...args),
    search: (...args: any[]) => mockSearch(...args),
    rechunk: (...args: any[]) => mockRechunk(...args),
  },
}));

const mockListWorkspaces = vi.fn();
const mockGetWorkspaceTree = vi.fn();
const mockCreateWorkspace = vi.fn();

vi.mock("@/services/workspace", () => ({
  listWorkspaces: (...args: any[]) => mockListWorkspaces(...args),
  createWorkspace: (...args: any[]) => mockCreateWorkspace(...args),
  getWorkspaceTree: (...args: any[]) => mockGetWorkspaceTree(...args),
}));

const mockListFolders = vi.fn();
const mockCreateFolder = vi.fn();
const mockMoveDocument = vi.fn();

vi.mock("@/services/folder", () => ({
  listFolders: (...args: any[]) => mockListFolders(...args),
  createFolder: (...args: any[]) => mockCreateFolder(...args),
  moveDocument: (...args: any[]) => mockMoveDocument(...args),
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
      subscribe: (_listener: (state: any, prev: any) => void) => () => {},
      getState: () => ({ items: [], unreadCount: 0 }),
    }
  ),
}));

vi.mock("@/components/EmbeddingModelSelect", () => ({
  default: () => <div data-testid="embedding-model-select-stub" />,
}));

// ─── Test data ──────────────────────────────────────────────────────────────

const sampleKB = {
  id: 42,
  name: "Workspace-Test-KB",
  description: "M38.2 fixture",
  tenant_id: 1,
  status: "active",
  embedding_model: "nomic-embed-text",
  embedding_model_config_id: 1,
  default_parser: "general",
  chunk_size: 500,
  chunk_overlap: 50,
  document_count: 3,
  workspace_id: 1,
  created_at: "2026-08-26T00:00:00Z",
};

const emptyListResponse = {
  data: { code: 200, message: "ok", data: [], total: 0, page: 1, page_size: 10 },
};

const sampleWorkspaces = {
  code: 200,
  message: "ok",
  data: [
    {
      id: 1,
      tenant_id: 1,
      name: "研发",
      knowledge_base_count: 1,
      created_at: "2026-08-26T00:00:00Z",
      updated_at: "2026-08-26T00:00:00Z",
    },
  ],
  total: 1,
  page: 1,
  page_size: 100,
};

const sampleTree = (wsId: number) => ({
  code: 200,
  message: "ok",
  data: {
    workspace: {
      id: wsId,
      tenant_id: 1,
      name: wsId === -1 ? "未分组" : "研发",
      created_at: "2026-08-26T00:00:00Z",
      updated_at: "2026-08-26T00:00:00Z",
    },
    knowledge_bases:
      wsId === -1
        ? []
        : [
            {
              id: 42,
              name: "Workspace-Test-KB",
              document_count: 3,
              folders: [
                {
                  id: 200,
                  name: "API",
                  document_count: 2,
                  children: [],
                },
              ],
            },
          ],
  },
});

const sampleFoldersTree = {
  code: 200,
  message: "ok",
  data: [
    {
      id: 200,
      parent_id: null,
      name: "API",
      order_index: 0,
      document_count: 2,
      children: [],
    },
  ],
};

const sampleDocs = {
  data: {
    code: 200,
    message: "ok",
    data: [
      {
        id: 1001,
        file_type: "md",
        file_size: 1234,
        status: "completed",
        chunk_count: 5,
        created_at: "2026-08-26T00:00:00Z",
        knowledge_base_id: 42,
        filename: "api-spec.md",
      },
    ],
  },
};

// ─── Wrapper ────────────────────────────────────────────────────────────────

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

// ─── Tests ──────────────────────────────────────────────────────────────────

describe("KnowledgePage — M38.2 workspace sidebar wiring", () => {
  beforeEach(() => {
    mockList.mockReset();
    mockGet.mockReset();
    mockGetDocuments.mockReset();
    mockCreate.mockReset();
    mockListWorkspaces.mockReset();
    mockGetWorkspaceTree.mockReset();
    mockCreateWorkspace.mockReset();
    mockListFolders.mockReset();
    mockCreateFolder.mockReset();
    mockMoveDocument.mockReset();

    mockList.mockResolvedValue(emptyListResponse);
    mockListWorkspaces.mockResolvedValue(sampleWorkspaces);
    mockGetWorkspaceTree.mockImplementation((id: number) =>
      Promise.resolve(sampleTree(id))
    );
    mockListFolders.mockResolvedValue(sampleFoldersTree);
    mockGetDocuments.mockResolvedValue(sampleDocs);
    mockGet.mockResolvedValue({
      data: { code: 200, message: "ok", data: sampleKB },
    });
  });

  it("挂载后 sidebar 拉了 workspaces list + workspace tree(-1 + 1)", async () => {
    render(
      <TestWrapper>
        <KnowledgePage />
      </TestWrapper>
    );

    await waitFor(() => {
      expect(mockListWorkspaces).toHaveBeenCalledOnce();
    });
    await waitFor(() => {
      expect(mockGetWorkspaceTree).toHaveBeenCalledWith(-1);
      expect(mockGetWorkspaceTree).toHaveBeenCalledWith(1);
    });
    expect(screen.getByTestId("workspace-tree-mock")).toBeInTheDocument();
  });

  it("MockTree 触发 onSelectKb → knowledgeApi.get(kbId) + knowledgeApi.getDocuments", async () => {
    render(
      <TestWrapper>
        <KnowledgePage />
      </TestWrapper>
    );

    await waitFor(() => {
      expect(screen.getByTestId("workspace-tree-mock")).toBeInTheDocument();
    });
    // 点 KB 42(workspace=1)
    fireEvent.click(screen.getByText("tree-select-kb-42"));

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith(42);
    });
    await waitFor(() => {
      const calls = mockGetDocuments.mock.calls.filter((c) => c[0] === 42);
      expect(calls.length).toBeGreaterThanOrEqual(1);
      // 默认 selectedFolderId=null → getDocuments(kbId, undefined)
      expect(calls[0][1]).toBeFalsy();
    });
  });

  it("MockTree 触发 onSelectFolder(1, 42, 200) → knowledgeApi.getDocuments(42, 200)", async () => {
    render(
      <TestWrapper>
        <KnowledgePage />
      </TestWrapper>
    );

    await waitFor(() => {
      expect(screen.getByTestId("workspace-tree-mock")).toBeInTheDocument();
    });
    // 先选 KB
    fireEvent.click(screen.getByText("tree-select-kb-42"));
    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith(42);
    });

    // 再选 folder 200
    fireEvent.click(screen.getByText("tree-select-folder-200"));

    await waitFor(() => {
      const calls = mockGetDocuments.mock.calls.filter(
        (c) => c[0] === 42 && c[1] === 200
      );
      expect(calls.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("MockTree 触发 onCreateWorkspace → CreateWorkspaceModal 打开", async () => {
    render(
      <TestWrapper>
        <KnowledgePage />
      </TestWrapper>
    );
    await waitFor(() => {
      expect(screen.getByTestId("workspace-tree-mock")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("tree-new-workspace"));

    await waitFor(() => {
      expect(screen.getByText("新建 workspace")).toBeInTheDocument();
    });
  });

  it("MockTree 触发 onCreateFolder(KB 已选中) → CreateFolderModal 打开", async () => {
    render(
      <TestWrapper>
        <KnowledgePage />
      </TestWrapper>
    );

    await waitFor(() => {
      expect(screen.getByTestId("workspace-tree-mock")).toBeInTheDocument();
    });
    // 先选 KB
    fireEvent.click(screen.getByText("tree-select-kb-42"));
    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith(42);
    });

    // 点 sidebar 新建 folder 按钮
    fireEvent.click(screen.getByText("tree-new-folder"));

    await waitFor(() => {
      expect(screen.getByText(/新建 folder \(KB #42\)/)).toBeInTheDocument();
    });
  });

  it("文档行点「移动」按钮 → MoveDocumentModal 打开,展示当前 doc id", async () => {
    render(
      <TestWrapper>
        <KnowledgePage />
      </TestWrapper>
    );

    await waitFor(() => {
      expect(screen.getByTestId("workspace-tree-mock")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("tree-select-kb-42"));

    await waitFor(() => {
      expect(screen.getByText("api-spec.md")).toBeInTheDocument();
    });

    // List action 里有「移动」按钮(行内 + 文档列表 modal 都共享)
    const moveButtons = screen.getAllByRole("button", { name: /移动/ });
    fireEvent.click(moveButtons[0]);

    await waitFor(() => {
      expect(screen.getByText(/移动文档 \(#1001\)/)).toBeInTheDocument();
    });
  });

  it("提交移动 → moveDocument(docId, payload),target_folder_id 反映当前 folder", async () => {
    mockMoveDocument.mockResolvedValue({ moved: true });
    render(
      <TestWrapper>
        <KnowledgePage />
      </TestWrapper>
    );

    await waitFor(() => {
      expect(screen.getByTestId("workspace-tree-mock")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("tree-select-kb-42"));
    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith(42);
    });
    // 切到 folder 200
    fireEvent.click(screen.getByText("tree-select-folder-200"));
    await waitFor(() => {
      expect(screen.getByText("api-spec.md")).toBeInTheDocument();
    });

    const moveButtons = screen.getAllByRole("button", { name: /移动/ });
    fireEvent.click(moveButtons[0]);
    await waitFor(() => {
      expect(screen.getByText(/移动文档 \(#1001\)/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /^移动$/ }));

    await waitFor(() => {
      expect(mockMoveDocument).toHaveBeenCalledOnce();
    });
    // currentFolderId=200 → target_folder_id=200
    expect(mockMoveDocument.mock.calls[0]).toEqual([
      1001,
      { target_folder_id: 200 },
    ]);
  });
});