import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ConfigProvider } from "antd";

// Mock the agent service module.
vi.mock("@/services/agent", () => ({
  agentApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    chat: vi.fn(),
  },
  MEMORY_POLICIES: [
    { value: "sliding_window", label: "滑动窗口" },
    { value: "token_limit", label: "Token 限制" },
    { value: "semantic_compression", label: "语义压缩" },
    { value: "none", label: "不使用记忆" },
  ],
  TOOL_CHOICE_MODES: [
    { value: "auto", label: "自动 (Auto)" },
    { value: "required", label: "必须调用 (Required)" },
    { value: "none", label: "不调用工具 (None)" },
    { value: "specific", label: "指定工具 (Specific)" },
  ],
}));

// Mock the models service (used by AgentFormModal internally).
vi.mock("@/services/models", () => ({
  modelsApi: { list: vi.fn() },
}));

// Mock the knowledge service (used by MultiKBSelector inside AgentFormModal
// since M21). The edit-modal test below opens the modal which now renders
// MultiKBSelector; without this mock, MultiKBSelector would make a real
// fetchAllKBOptions call to the backend.
vi.mock("@/services/knowledge", () => ({
  knowledgeApi: {
    list: vi.fn().mockResolvedValue({
      data: {
        code: 200,
        data: [],
        total: 0,
        page: 1,
        page_size: 100,
      },
    }),
  },
}));

// Mock antd message.
vi.mock("antd", async () => {
  const actual = await vi.importActual<typeof import("antd")>("antd");
  return {
    ...actual,
    message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  };
});

import { agentApi } from "@/services/agent";
import AgentPage from "@/app/dashboard/agent/page";
import type { Agent } from "@/types/api";

const Wrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{children}</ConfigProvider>
);

const makeAgent = (overrides: Partial<Agent> = {}): Agent =>
  ({
    id: 1,
    name: "alpha",
    description: "first",
    prompt_template: "hi {'{input}'}",
    model_name: "gpt-4o",
    temperature: 0,
    is_active: true,
    memory_policy: "sliding_window",
    memory_window_size: 20,
    memory_max_tokens: 4000,
    memory_compression: false,
    tool_choice: "auto",
    tool_choice_required: false,
    allowed_tools: [],
    tenant_id: 1,
    created_at: "2026-06-06T00:00:00",
    ...overrides,
  } as Agent);

describe("AgentPage list interactions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(agentApi.list).mockResolvedValue({
      data: { code: 200, data: [makeAgent({ id: 1 }), makeAgent({ id: 2, is_active: false, name: "beta" })], total: 2, page: 1, page_size: 10 },
    } as any);
    vi.mocked(agentApi.update).mockResolvedValue({ data: { code: 200, data: makeAgent() } } as any);
  });

  it("toggling the is_active Switch calls agentApi.update with the new value", async () => {
    render(<AgentPage />, { wrapper: Wrapper });
    // Wait for the list to render
    await waitFor(() => expect(screen.getByText("alpha")).toBeTruthy());
    // There should be 2 switches (one per row)
    const switches = screen.getAllByRole("switch");
    expect(switches.length).toBe(2);
    // First switch is checked (alpha is_active=true), toggle it off
    expect(switches[0]).toBeChecked();
    fireEvent.click(switches[0]);
    await waitFor(() => {
      expect(agentApi.update).toHaveBeenCalledWith(1, { is_active: false });
    });
  });

  it("Switch toggle rolls back when agentApi.update rejects", async () => {
    vi.mocked(agentApi.update).mockRejectedValueOnce(new Error("boom"));
    render(<AgentPage />, { wrapper: Wrapper });
    await waitFor(() => expect(screen.getByText("alpha")).toBeTruthy());
    const switches = screen.getAllByRole("switch");

    // Optimistic: click flips the switch immediately (before the API call resolves/rejects)
    fireEvent.click(switches[0]);
    expect(switches[0]).not.toBeChecked();

    // Rollback: after rejection, the switch flips back
    await waitFor(() => {
      expect(screen.getAllByRole("switch")[0]).toBeChecked();
    });
    // Error toast was shown (spec 3.4)
    const { message } = await import("antd");
    expect(message.error).toHaveBeenCalledWith("状态切换失败");
  });

  it("clicking the 编辑 button opens the edit modal pre-filled with that row's data", async () => {
    render(<AgentPage />, { wrapper: Wrapper });
    await waitFor(() => expect(screen.getByText("alpha")).toBeTruthy());
    // First row's edit button
    const editButtons = screen.getAllByRole("button", { name: "编辑" });
    expect(editButtons.length).toBe(2);
    fireEvent.click(editButtons[0]);
    // Edit modal title appears
    await waitFor(() => expect(screen.getByText("编辑Agent")).toBeTruthy());
    // Pre-filled with alpha's name
    const nameInput = screen.getByPlaceholderText("请输入Agent名称") as HTMLInputElement;
    expect(nameInput.value).toBe("alpha");
  });
});

describe("AgentPage chat modal markdown rendering", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(agentApi.list).mockResolvedValue({
      data: { code: 200, data: [makeAgent()], total: 1, page: 1, page_size: 10 },
    } as any);
  });

  it("renders assistant response as Markdown (heading, bold, list), not raw ** / ##", async () => {
    // Real-world example: the response the user saw was a long markdown
    // doc that the modal dumped verbatim. Lock in that headings render as
    // <h2>, **bold** as <strong>, and - items as <li>.
    const md = [
      "## 招聘岗位的显性AI渗透率",
      "",
      "**结论**:渗透率仍偏低,约 3%。",
      "",
      "- 2020 年:0.8%",
      "- 2024 年:3.3%",
    ].join("\n");

    vi.mocked(agentApi.chat).mockResolvedValueOnce({
      data: { code: 200, data: { response: md, conversation_id: 100 } },
    } as any);

    render(<AgentPage />, { wrapper: Wrapper });
    await waitFor(() => expect(screen.getByText("alpha")).toBeTruthy());

    // Open chat modal for the only row
    fireEvent.click(screen.getByRole("button", { name: "对话" }));
    await waitFor(() =>
      expect(screen.getByText(/与.*alpha.*对话/)).toBeTruthy()
    );

    // Type a message and send
    const input = screen.getByPlaceholderText("输入消息...") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "请解释一下" } });
    // AntD <Button icon={<SendOutlined />}>发送</Button> doesn't always
    // expose "发送" as the button's accessible name (icon may contribute),
    // so locate the button by its visible text content instead.
    const sendButton = screen.getByText("发送").closest("button");
    expect(sendButton).toBeTruthy();
    fireEvent.click(sendButton as HTMLElement);

    // Markdown actually rendered (not raw text):
    //   ## title  → <h2>
    //   **结论**  → <strong>结论</strong>
    //   - item    → <li>
    await waitFor(() => {
      expect(
        screen.getByRole("heading", {
          level: 2,
          name: /招聘岗位的显性AI渗透率/,
        })
      ).toBeTruthy();
    });
    expect(screen.getByText("结论").tagName).toBe("STRONG");
    expect(screen.getByText("2020 年:0.8%").tagName).toBe("LI");
    expect(screen.getByText("2024 年:3.3%").tagName).toBe("LI");

    // And the raw markdown markers must NOT leak into the DOM as text.
    // (If someone reverts the fix and re-renders {msg.content}, these
    // markers would appear literally next to the rendered content.)
    expect(screen.queryByText(/^\*\*结论\*\*/)).toBeNull();
  });
});
