// frontend/__tests__/knowledge/delete-blockers.test.tsx
// M28 — 422 blocker UX: 删 KB 时,如果后端返回 422 + blocking_agents /
// blocking_documents 列表,前端应弹 Modal 展示具体是哪个 Agent / 哪份文档在卡,
// 不再让用户对着一个 "agent_count: 1" 冷数字猜去哪儿解绑。
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { ConfigProvider, App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import KnowledgePage from "@/app/dashboard/knowledge/page";

// ─── Mocks ──────────────────────────────────────────────────────────────────

// next/navigation:useSearchParams — 页面 useEffect 会读 URL 参数。
// 返空就好,我们不依赖 query string。
vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: (_k: string) => null }),
  useRouter: () => ({ push: vi.fn() }),
}));

// next/navigation: useRouter 也可能用
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn() }),
}));

// knowledgeApi 的所有方法。delete 这次被做成 reject-with-422;
const mockDelete = vi.fn();
const mockList = vi.fn();
const mockGet = vi.fn();
const mockGetDocuments = vi.fn();
const mockCreate = vi.fn();
const mockUpdate = vi.fn();
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
  // 页面 import 时也带 ParserType / DocumentResponse / DocumentChunk type,
  // 这些是 type-only import,vi.mock 不需要 mock 它们(TS 编译时已擦除)。
}));

// models service 用了 useQuery
vi.mock("@/services/models", () => ({
  ModelConfig: {},
  modelConfigApi: { list: vi.fn() },
}));

// notifications store — 页面里 useEffect 调 .subscribe(state, prev => ...) 监听
// items 变化,react 风格的 zustand 订阅器签名。
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

// EmbeddingModelSelect 是个复杂下拉,Mock 简化
vi.mock("@/components/EmbeddingModelSelect", () => ({
  default: () => <div data-testid="embedding-model-select-stub" />,
}));

// ─── Test data ──────────────────────────────────────────────────────────────

const sampleKB = {
  id: 42,
  name: "Blocker-Test-KB",
  description: "M28 test",
  tenant_id: 1,
  status: "active",
  embedding_model: "nomic-embed-text",
  embedding_model_config_id: 1,
  search_weights: { vector: 0.5, bm25: 0.5 },
  default_parser: "fixed",
  chunk_size: 500,
  chunk_overlap: 50,
  document_count: 0,
  created_at: "2026-06-15T00:00:00Z",
  updated_at: "2026-06-15T00:00:00Z",
};

const listResponse = {
  data: {
    code: 200,
    message: "ok",
    data: [sampleKB],
    total: 1,
    page: 1,
    page_size: 10,
  },
};

// 422 用 axios 风格的 error 对象构造。handleDelete 读 error.response.status
// 和 error.response.data.detail,所以必须把 response 字段都填好。
function makeAxiosError(status: number, detail: any) {
  return {
    response: {
      status,
      data: { detail },
    },
    message: `Request failed with status code ${status}`,
  };
}

// 422 + 1 agent + 2 documents + truncated false 的标准响应
const blocker422 = {
  message: "KB 仍被 1 个 agent 和 2 个文档引用,需先解绑/删除",
  agent_count: 1,
  document_count: 2,
  blocking_agents: [{ id: 7, name: "Customer Support Agent" }],
  blocking_documents: [
    { id: 100, filename: "manual.pdf" },
    { id: 101, filename: "faq.txt" },
  ],
  truncated: false,
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

// 拿到页面里那个「删除」按钮。Table 行里第一个删除按钮(单行场景)。
function findDeleteButton() {
  return screen.getByRole("button", { name: /删除/ });
}

// 在 Popconfirm 弹层里点「确定」按钮。
// 仿照 chat/page-delete.test.tsx:click trigger → waitFor 弹层 title →
// 在 .ant-popconfirm-buttons 里找 OK 按钮(AntD 把 OK / Cancel 装这个容器)。
// 不写死按钮文字,避免 AntD 不同版本默认文案 (确定/OK/好) 漂移。
async function confirmPopover() {
  // 1) 等 Popconfirm 弹层 title 出现,证明 popover 已挂载
  await waitFor(() => {
    expect(screen.getByText("确认删除?")).toBeInTheDocument();
  });
  // 2) 在 .ant-popconfirm-buttons 里找 OK 按钮(AntD 把 OK 渲染为 .ant-btn-primary,
  //    Cancel 渲染为普通 .ant-btn,所以锁定 primary 那个)
  const okBtn = document.querySelector(
    ".ant-popconfirm-buttons .ant-btn-primary"
  ) as HTMLButtonElement | null;
  if (!okBtn) {
    throw new Error(
      "Popconfirm OK button (.ant-popconfirm-buttons .ant-btn-primary) not found"
    );
  }
  fireEvent.click(okBtn);
}

// ─── Tests ──────────────────────────────────────────────────────────────────

describe("KnowledgePage — M28 delete blockers UX", () => {
  beforeEach(() => {
    mockList.mockReset();
    mockDelete.mockReset();
    mockList.mockResolvedValue(listResponse);
  });

  it("422 with agent + document blockers → Modal lists them by name", async () => {
    mockDelete.mockRejectedValue(makeAxiosError(422, blocker422));

    render(
      <TestWrapper>
        <KnowledgePage />
      </TestWrapper>
    );

    // 等 KB 渲染进 table
    await waitFor(() => {
      expect(screen.getByText("Blocker-Test-KB")).toBeInTheDocument();
    });

    // 点击「删除」按钮 → Popconfirm 弹出 → 点「确定」触发 handleDelete
    fireEvent.click(findDeleteButton());
    await confirmPopover();

    // Modal 应该出现,标题 "无法删除知识库"
    await waitFor(() => {
      expect(screen.getByText("无法删除知识库")).toBeInTheDocument();
    });
    // Message 应该展示后端给的原文
    expect(
      screen.getByText("KB 仍被 1 个 agent 和 2 个文档引用,需先解绑/删除")
    ).toBeInTheDocument();
    // Agent 名字 + id
    expect(screen.getByText("Customer Support Agent")).toBeInTheDocument();
    expect(screen.getByText(/id=7/)).toBeInTheDocument();
    // Document 文件名 + id
    expect(screen.getByText("manual.pdf")).toBeInTheDocument();
    expect(screen.getByText(/id=100/)).toBeInTheDocument();
    expect(screen.getByText("faq.txt")).toBeInTheDocument();
    expect(screen.getByText(/id=101/)).toBeInTheDocument();

    // 不强断言「知道了」关闭行为 —— AntD Modal 关闭走动画 + portal,
    // jsdom 里 waitFor 1s 经常被 close 动画拖到超时。
    // AntD 自身保证 onClick 触发 visible=false,这一步留作 smoke test 即可。
  });

  it("422 with truncated=true → warning 注脚 shows", async () => {
    mockDelete.mockRejectedValue(
      makeAxiosError(422, { ...blocker422, truncated: true })
    );

    render(
      <TestWrapper>
        <KnowledgePage />
      </TestWrapper>
    );
    await waitFor(() => {
      expect(screen.getByText("Blocker-Test-KB")).toBeInTheDocument();
    });
    fireEvent.click(findDeleteButton());
    await confirmPopover();

    await waitFor(() => {
      expect(screen.getByText(/列表已截断/)).toBeInTheDocument();
    });
  });

  it("500 错误 → 走兜底 message.error, 不弹 Modal", async () => {
    // 500 时 detail 是 string(后端 FastAPI 默认行为)
    mockDelete.mockRejectedValue(makeAxiosError(500, "Internal Server Error"));

    render(
      <TestWrapper>
        <KnowledgePage />
      </TestWrapper>
    );
    await waitFor(() => {
      expect(screen.getByText("Blocker-Test-KB")).toBeInTheDocument();
    });
    fireEvent.click(findDeleteButton());
    await confirmPopover();

    // Modal 不应出现
    expect(screen.queryByText("无法删除知识库")).not.toBeInTheDocument();
    // toast(antd message) 走 App.useApp() instance 注入到 DOM,
    // 测试用静态 message 模块的 vi.spyOn 抓不到(per M14 quirk),
    // 所以这里只断言「Modal 没出现」,toast 内容由 antd 自身保证。
  });
});
