// frontend/__tests__/chat/page-agent-binding.test.tsx
// Page-level tests for /dashboard/chat: agent selection on create + top
// switcher + sidebar badge + send payload. Reuses the mock pattern from
// page-delete.test.tsx; switches TestWrapper to <App> because the page
// now uses App.useApp() for messages.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { App, ConfigProvider, message } from "antd";

const mockListConversations = vi.fn();
const mockCreateConversation = vi.fn();
const mockGetMessages = vi.fn();
const mockDeleteConversation = vi.fn();
const mockUploadAttachment = vi.fn();
const mockStreamChat = vi.fn();
const mockUpdateConversation = vi.fn();
vi.mock("@/services/chat", () => ({
  chatApi: {
    listConversations: (...args: any[]) => mockListConversations(...args),
    createConversation: (...args: any[]) => mockCreateConversation(...args),
    getMessages: (...args: any[]) => mockGetMessages(...args),
    deleteConversation: (...args: any[]) => mockDeleteConversation(...args),
    uploadAttachment: (...args: any[]) => mockUploadAttachment(...args),
    streamChat: (...args: any[]) => mockStreamChat(...args),
    updateConversation: (...args: any[]) => mockUpdateConversation(...args),
  },
}));

const mockAgentList = vi.fn();
vi.mock("@/services/agent", () => ({
  agentApi: { list: (...args: any[]) => mockAgentList(...args) },
}));

import ChatPage from "@/app/dashboard/chat/page";
import type { Conversation } from "@/types/chat";
import type { Agent } from "@/types/api";

const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>
    <App>{children}</App>
  </ConfigProvider>
);

const buildList = (list: Conversation[]) => ({
  data: { code: 200, message: "ok", data: list },
});

const sampleConv = (id: number, agent_id?: number, agent_name?: string): Conversation => ({
  id,
  title: `conv-${id}`,
  agent_id,
  agent_name,
  created_at: "2026-06-07T10:00:00Z",
  updated_at: "2026-06-07T10:00:00Z",
} as unknown as Conversation);

const sampleAgent = (id: number, name: string, is_active = true): Agent => ({
  id, name,
  prompt_template: "p", model_name: "qwen2.5:7b", temperature: 0,
  tenant_id: 1, is_active,
  created_at: "2026-06-07T10:00:00Z",
} as unknown as Agent);

describe("ChatPage new-conversation modal", () => {
  beforeEach(() => {
    mockListConversations.mockReset();
    mockCreateConversation.mockReset();
    mockGetMessages.mockReset();
    mockDeleteConversation.mockReset();
    mockUploadAttachment.mockReset();
    mockStreamChat.mockReset();
    mockUpdateConversation.mockReset();
    mockAgentList.mockReset();

    mockListConversations.mockResolvedValue(buildList([]));
    mockGetMessages.mockResolvedValue({
      data: { code: 200, message: "ok", data: [] },
    });
    mockAgentList.mockResolvedValue({
      data: {
        code: 200, message: "ok",
        data: [sampleAgent(1, "translator"), sampleAgent(2, "coder")],
      },
    });
    mockCreateConversation.mockImplementation((data) =>
      Promise.resolve({
        data: {
          code: 200, message: "ok",
          data: sampleConv(99, data?.agent_id, data?.agent_id === 1 ? "translator" : undefined),
        },
      })
    );

    vi.spyOn(message, "success").mockImplementation((() => ({})) as any);
    vi.spyOn(message, "error").mockImplementation((() => ({})) as any);
  });

  it("opens modal with 'default' selected when + button is clicked", async () => {
    render(<ChatPage />, { wrapper: TestWrapper });
    await waitFor(() => expect(mockAgentList).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: /新建对话/ }));

    // Modal title appears (matches both the sidebar button label and the
    // modal title; after click there should be 2+ elements with this text).
    await waitFor(() =>
      expect(screen.getAllByText("新建对话").length).toBeGreaterThanOrEqual(2)
    );
    // Default option is present
    expect(screen.getByText(/默认 \(使用 tenant 默认模型\)/)).toBeTruthy();
  });

  it("create with selected agent calls chatApi.createConversation with agent_id", async () => {
    render(<ChatPage />, { wrapper: TestWrapper });
    await waitFor(() => expect(mockAgentList).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: /新建对话/ }));
    await waitFor(() =>
      expect(screen.getAllByText("新建对话").length).toBeGreaterThanOrEqual(2)
    );

    // Open the Select and pick translator (id=1)
    const select = screen.getByRole("combobox");
    fireEvent.mouseDown(select);
    const option = await screen.findByText("🤖 translator");
    fireEvent.click(option);

    // Click 创建
    fireEvent.click(screen.getByRole("button", { name: /创建/ }));

    await waitFor(() =>
      expect(mockCreateConversation).toHaveBeenCalledWith({ agent_id: 1 })
    );
  });

  it("create with default selected calls chatApi.createConversation without agent_id", async () => {
    render(<ChatPage />, { wrapper: TestWrapper });
    await waitFor(() => expect(mockAgentList).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: /新建对话/ }));
    await waitFor(() =>
      expect(screen.getAllByText("新建对话").length).toBeGreaterThanOrEqual(2)
    );

    // Click 创建 without changing the default selection
    fireEvent.click(screen.getByRole("button", { name: /创建/ }));

    await waitFor(() =>
      expect(mockCreateConversation).toHaveBeenCalledWith({ agent_id: undefined })
    );
  });

  it("shows empty hint when tenant has 0 active agents", async () => {
    mockAgentList.mockResolvedValue({
      data: { code: 200, message: "ok", data: [] },
    });

    render(<ChatPage />, { wrapper: TestWrapper });
    await waitFor(() => expect(mockAgentList).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: /新建对话/ }));
    await waitFor(() =>
      expect(screen.getAllByText("新建对话").length).toBeGreaterThanOrEqual(2)
    );

    // The "先去 AI Agent 页面创建一个" hint appears when agents.length === 0
    expect(screen.getByText(/先到/)).toBeTruthy();
  });

  it("keeps modal open and shows error toast when createConversation rejects", async () => {
    mockCreateConversation.mockRejectedValue(new Error("network down"));

    render(<ChatPage />, { wrapper: TestWrapper });
    await waitFor(() => expect(mockAgentList).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: /新建对话/ }));
    // Modal opened
    expect(screen.getAllByText("新建对话").length).toBeGreaterThanOrEqual(2);

    // Click 创建 — should fail
    fireEvent.click(screen.getByRole("button", { name: /创建/ }));

    await waitFor(() => {
      expect(mockCreateConversation).toHaveBeenCalled();
    });
    // Modal MUST stay open — user can retry
    await waitFor(() => {
      expect(screen.getAllByText("新建对话").length).toBeGreaterThanOrEqual(2);
    });
    // Error toast was shown — assert by DOM (the `vi.spyOn(message, "error")` won't catch App.useApp() instance)
    await waitFor(() => {
      expect(screen.getByText("创建对话失败")).toBeTruthy();
    });
  });
});

describe("ChatPage top agent switcher", () => {
  beforeEach(() => {
    mockListConversations.mockReset();
    mockCreateConversation.mockReset();
    mockGetMessages.mockReset();
    mockDeleteConversation.mockReset();
    mockUploadAttachment.mockReset();
    mockStreamChat.mockReset();
    mockUpdateConversation.mockReset();
    mockAgentList.mockReset();

    mockGetMessages.mockResolvedValue({
      data: { code: 200, message: "ok", data: [] },
    });
    mockAgentList.mockResolvedValue({
      data: {
        code: 200, message: "ok",
        data: [sampleAgent(1, "translator"), sampleAgent(2, "coder")],
      },
    });
    mockUpdateConversation.mockImplementation((id, data) =>
      Promise.resolve({
        data: {
          code: 200, message: "ok",
          data: sampleConv(id, data?.agent_id ?? null, data?.agent_id === 1 ? "translator" : "coder"),
        },
      })
    );

    vi.spyOn(message, "success").mockImplementation((() => ({})) as any);
    vi.spyOn(message, "error").mockImplementation((() => ({})) as any);
  });

  it("switching agent calls updateConversation and updates local state", async () => {
    mockListConversations.mockResolvedValue(
      buildList([sampleConv(7, 1, "translator")])
    );

    render(<ChatPage />, { wrapper: TestWrapper });
    await waitFor(() => expect(mockAgentList).toHaveBeenCalled());
    // Click into the conversation to make it currentConv
    await waitFor(() => expect(screen.getByText("conv-7")).toBeTruthy());
    fireEvent.click(screen.getByText("conv-7"));

    // The top switcher is a combobox. After click, the conversation becomes
    // current and the switcher appears. The new-conv modal is closed at this
    // point, so the only combobox on the page is the switcher.
    const switcher = screen.getAllByRole("combobox").find((el) => {
      // Filter out the one inside a modal (shouldn't exist here, but be safe)
      return !el.closest(".ant-modal");
    });
    expect(switcher).toBeTruthy();
    fireEvent.mouseDown(switcher!);

    const opt = await screen.findByText("coder");
    fireEvent.click(opt);

    await waitFor(() =>
      expect(mockUpdateConversation).toHaveBeenCalledWith(7, { agent_id: 2 })
    );
  });

  it("failed update keeps the current selection (no state change)", async () => {
    mockListConversations.mockResolvedValue(
      buildList([sampleConv(7, 1, "translator")])
    );
    mockUpdateConversation.mockResolvedValue({
      data: { code: 500, message: "boom", data: null },
    });

    render(<ChatPage />, { wrapper: TestWrapper });
    await waitFor(() => expect(mockAgentList).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("conv-7")).toBeTruthy());
    fireEvent.click(screen.getByText("conv-7"));

    const switcher = screen.getAllByRole("combobox").find((el) =>
      !el.closest(".ant-modal")
    );
    expect(switcher).toBeTruthy();
    fireEvent.mouseDown(switcher!);
    const opt = await screen.findByText("coder");
    fireEvent.click(opt);

    await waitFor(() =>
      expect(mockUpdateConversation).toHaveBeenCalledWith(7, { agent_id: 2 })
    );
    // Switcher's displayed value is still "translator" (state unchanged on
    // failure). Target the .ant-select-selection-item specifically — the
    // dropdown's options (which include "translator" and "coder") are also
    // still mounted in the DOM, so a plain getByText / getByTitle would
    // match multiple elements.
    await waitFor(() => {
      const item = document.querySelector(".ant-select-selection-item");
      expect(item).toBeTruthy();
      expect(item?.getAttribute("title")).toBe("translator");
    });
  });
});

describe("ChatPage AgentKBBanner (M21 T19)", () => {
  beforeEach(() => {
    mockListConversations.mockReset();
    mockGetMessages.mockReset();
    mockAgentList.mockReset();
    mockGetMessages.mockResolvedValue({
      data: { code: 200, message: "ok", data: [] },
    });
    vi.spyOn(message, "success").mockImplementation((() => ({})) as any);
    vi.spyOn(message, "error").mockImplementation((() => ({})) as any);
  });

  it("shows KB banner on conversation bound to a KB-having agent", async () => {
    mockListConversations.mockResolvedValue(
      buildList([sampleConv(7, 1, "agent-with-kb")])
    );
    mockAgentList.mockResolvedValue({
      data: {
        code: 200, message: "ok",
        data: [{
          ...sampleAgent(1, "agent-with-kb"),
          knowledge_bases: [{ id: 10, name: "Sales", status: "active" }],
        }],
      },
    });

    render(<ChatPage />, { wrapper: TestWrapper });
    await waitFor(() => expect(mockAgentList).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("conv-7")).toBeTruthy());
    fireEvent.click(screen.getByText("conv-7"));

    // Banner should appear showing the KB name
    await waitFor(() => {
      expect(screen.getByText("Sales")).toBeInTheDocument();
    });
    // Banner label is also present
    expect(screen.getByText("已加载知识库:")).toBeInTheDocument();
  });

  it("banner close hides it for the session", async () => {
    mockListConversations.mockResolvedValue(
      buildList([sampleConv(7, 1, "agent")])
    );
    mockAgentList.mockResolvedValue({
      data: {
        code: 200, message: "ok",
        data: [{
          ...sampleAgent(1, "agent"),
          knowledge_bases: [{ id: 10, name: "KB1", status: "active" }],
        }],
      },
    });

    render(<ChatPage />, { wrapper: TestWrapper });
    await waitFor(() => expect(mockAgentList).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("conv-7")).toBeTruthy());
    fireEvent.click(screen.getByText("conv-7"));

    // Wait for banner to appear
    await screen.findByText("KB1");

    // Find the close button inside the banner. The banner has a unique
    // style attribute on its container; the close button is the only one
    // button inside that container.
    const banner = screen.getByText("已加载知识库:").closest("div[style*='background']") as HTMLElement;
    expect(banner).toBeTruthy();
    const closeBtn = banner.querySelector("button") as HTMLButtonElement;
    expect(closeBtn).toBeTruthy();
    fireEvent.click(closeBtn);

    // Banner should be gone
    await waitFor(() => {
      expect(screen.queryByText("KB1")).not.toBeInTheDocument();
    });
  });
});

describe("ChatPage sidebar agent badge", () => {
  beforeEach(() => {
    mockListConversations.mockReset();
    mockGetMessages.mockReset();
    mockAgentList.mockReset();
    mockGetMessages.mockResolvedValue({
      data: { code: 200, message: "ok", data: [] },
    });
    mockAgentList.mockResolvedValue({
      data: { code: 200, message: "ok", data: [] },
    });
    vi.spyOn(message, "success").mockImplementation((() => ({})) as any);
    vi.spyOn(message, "error").mockImplementation((() => ({})) as any);
  });

  it("shows agent_name badge for conv with agent_id, hides for default-only", async () => {
    mockListConversations.mockResolvedValue(
      buildList([
        sampleConv(1, 5, "translator"),
        sampleConv(2, undefined, undefined),
      ])
    );

    render(<ChatPage />, { wrapper: TestWrapper });
    await waitFor(() => expect(mockAgentList).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("conv-1")).toBeTruthy());

    // Sidebar renders the agent_name as a Tag with first 8 chars
    expect(screen.getByText("translat")).toBeTruthy();
    // The default-only conv (conv-2) shows no Tag with agent name
    // Use queryAllByText (returns [] on no match — getAllByText throws)
    const tags = screen.queryAllByText(/^translator$/);
    // The badge shows first 8 chars; full name should NOT appear as a Tag
    expect(tags.length).toBe(0);
  });
});

describe("ChatPage send payload includes agent_id from currentConv", () => {
  beforeEach(() => {
    mockListConversations.mockReset();
    mockGetMessages.mockReset();
    mockAgentList.mockReset();
    mockStreamChat.mockReset();
    mockUploadAttachment.mockReset();
    mockGetMessages.mockResolvedValue({
      data: { code: 200, message: "ok", data: [] },
    });
    mockAgentList.mockResolvedValue({
      data: { code: 200, message: "ok", data: [] },
    });
    // Fake SSE-like response body that completes immediately
    const fakeBody = {
      getReader: () => ({
        read: async () => ({ done: true, value: undefined }),
      }),
    };
    mockStreamChat.mockResolvedValue(fakeBody as any);
    vi.spyOn(message, "success").mockImplementation((() => ({})) as any);
    vi.spyOn(message, "error").mockImplementation((() => ({})) as any);
  });

  it("sends agent_id from currentConv when sending a message", async () => {
    mockListConversations.mockResolvedValue(
      buildList([sampleConv(11, 5, "translator")])
    );

    render(<ChatPage />, { wrapper: TestWrapper });
    await waitFor(() => expect(mockAgentList).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("conv-11")).toBeTruthy());
    fireEvent.click(screen.getByText("conv-11"));

    // Type a message and press Enter
    const input = screen.getByPlaceholderText("输入消息...") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "hello" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

    await waitFor(() => expect(mockStreamChat).toHaveBeenCalled());
    const call = mockStreamChat.mock.calls[0];
    const body = call[0]; // first arg is the data object
    expect(body.conversation_id).toBe(11);
    expect(body.agent_id).toBe(5);
  });
});
