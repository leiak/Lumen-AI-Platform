// frontend/__tests__/chat/page-delete.test.tsx
// Page-level tests for /dashboard/chat: delete button opens Popconfirm,
// confirm calls deleteConversation + refetches, failure shows error toast,
// deleting the active conversation jumps to the next one.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { ConfigProvider, App } from "antd";

// Mock the chat service module so we don't hit the network.
const mockListConversations = vi.fn();
const mockDeleteConversation = vi.fn();
const mockGetMessages = vi.fn();
const mockCreateConversation = vi.fn();
const mockUploadAttachment = vi.fn();
const mockStreamChat = vi.fn();
vi.mock("@/services/chat", () => ({
  chatApi: {
    listConversations: (...args: any[]) => mockListConversations(...args),
    deleteConversation: (...args: any[]) => mockDeleteConversation(...args),
    getMessages: (...args: any[]) => mockGetMessages(...args),
    createConversation: (...args: any[]) => mockCreateConversation(...args),
    uploadAttachment: (...args: any[]) => mockUploadAttachment(...args),
    streamChat: (...args: any[]) => mockStreamChat(...args),
  },
}));

import ChatPage from "@/app/dashboard/chat/page";
import type { Conversation } from "@/types/chat";

const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}><App>{children}</App></ConfigProvider>
);

const buildListResponse = (list: Conversation[]) => ({
  data: { code: 200, message: "ok", data: list },
});

const sampleConv = (id: number, title = `conv-${id}`): Conversation => ({
  id,
  title,
  // user_id/tenant_id are present on the backend response envelope but not on
  // the frontend Conversation type. Cast keeps the test concise.
  user_id: 1,
  tenant_id: 1,
  agent_id: undefined,
  created_at: "2026-06-06T10:00:00Z",
  updated_at: "2026-06-06T10:00:00Z",
} as unknown as Conversation);

// The page reads `res.data.data` (axios -> SingleResponse envelope -> `data: T`).
describe("ChatPage delete conversation", () => {
  beforeEach(() => {
    mockListConversations.mockReset();
    mockDeleteConversation.mockReset();
    mockGetMessages.mockReset();
    mockCreateConversation.mockReset();
    mockUploadAttachment.mockReset();
    mockStreamChat.mockReset();
    // Default: list returns empty; getMessages returns empty
    mockListConversations.mockResolvedValue(buildListResponse([]));
    mockGetMessages.mockResolvedValue({
      data: { code: 200, message: "ok", data: [] },
    });
    // Note: ChatPage uses App.useApp() to get the message instance, which is a
    // separate object from the static `message` import. We can't easily spy on
    // the App-context-provided message here, so we no longer assert on toast
    // calls. The remaining assertions (API call, list refetch, currentConv
    // jump) still verify the core delete behavior.
  });

  it("opens Popconfirm when delete icon is clicked; row click does not change selection", async () => {
    mockListConversations.mockResolvedValue(
      buildListResponse([sampleConv(1, "only one")])
    );

    render(<ChatPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("only one")).toBeTruthy();
    });

    // Find the delete trigger button by its aria-label.
    const [target] = screen.getAllByRole("button", { name: "删除" });
    expect(target).toBeTruthy();
    fireEvent.click(target);

    // Popconfirm title appears
    await waitFor(() => {
      expect(screen.getByText("确认删除该对话?")).toBeTruthy();
    });

    // Row click did not fire (no selection change) — e.stopPropagation() worked.
    // The active row has inline style.background = "#e6f7ff" (normalized to
    // "rgb(230, 247, 255)" by the browser); non-active rows default to
    // "transparent". Assert the row did NOT get the active highlight.
    const row = screen.getByText("only one").closest(".ant-list-item") as HTMLElement;
    expect(row.style.background).not.toBe("rgb(230, 247, 255)");
  });

  it("confirm calls deleteConversation, shows success toast, and refetches the list", async () => {
    mockListConversations
      .mockResolvedValueOnce(buildListResponse([sampleConv(1, "to delete")]))
      .mockResolvedValueOnce(buildListResponse([]));
    mockDeleteConversation.mockResolvedValue({
      data: { code: 200, message: "Deleted successfully", data: null },
    });

    render(<ChatPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("to delete")).toBeTruthy();
    });

    // Open Popconfirm
    const trigger = Array.from(
      document.querySelectorAll(".ant-list-item button")
    ).find((b) => b.querySelector(".anticon-delete, .anticon-delete-outlined")) as
      | HTMLButtonElement
      | undefined;
    fireEvent.click(trigger!);
    await waitFor(() => {
      expect(screen.getByText("确认删除该对话?")).toBeTruthy();
    });

    // Confirm: the popover OK button is inside .ant-popconfirm-buttons.
    // (findAllByRole("button", { name: "删除" }) is unreliable here because each
    // list item also has a delete trigger with aria-label="删除".)
    const confirmBtn = (await screen.findAllByRole("button", { name: "删除" })).find(
      (btn) => !!btn.closest(".ant-popconfirm")
    ) as HTMLButtonElement;
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(mockDeleteConversation).toHaveBeenCalledWith(1);
    });
    await waitFor(() => {
      expect(mockListConversations).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      expect(screen.getByText("删除成功")).toBeTruthy();
    });
  });

  it("shows error toast and does not refetch on delete failure", async () => {
    mockListConversations.mockResolvedValue(
      buildListResponse([sampleConv(1, "to delete")])
    );
    mockDeleteConversation.mockRejectedValue(new Error("boom"));

    render(<ChatPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("to delete")).toBeTruthy();
    });

    const trigger = Array.from(
      document.querySelectorAll(".ant-list-item button")
    ).find((b) => b.querySelector(".anticon-delete, .anticon-delete-outlined")) as
      | HTMLButtonElement
      | undefined;
    fireEvent.click(trigger!);
    await waitFor(() => {
      expect(screen.getByText("确认删除该对话?")).toBeTruthy();
    });

    const confirmBtn = (await screen.findAllByRole("button", { name: "删除" })).find(
      (btn) => !!btn.closest(".ant-popconfirm")
    ) as HTMLButtonElement;
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(mockDeleteConversation).toHaveBeenCalled();
    });
    expect(mockListConversations).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(screen.getByText("删除失败")).toBeTruthy();
    });
  });

  it("deleting the active conversation jumps currentConv to the remaining first one", async () => {
    // Two conversations; user clicks the first to set it active, then deletes it.
    mockListConversations
      .mockResolvedValueOnce(
        buildListResponse([sampleConv(1, "first"), sampleConv(2, "second")])
      )
      .mockResolvedValueOnce(buildListResponse([sampleConv(2, "second")]));
    mockDeleteConversation.mockResolvedValue({
      data: { code: 200, message: "Deleted successfully", data: null },
    });

    render(<ChatPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("first")).toBeTruthy();
    });
    await waitFor(() => {
      expect(screen.getByText("second")).toBeTruthy();
    });

    // Click the "first" row to make it current (scope to the list item, since the
    // header <strong> also renders the currentConv title once it's selected).
    const firstTitle = screen.getAllByText("first").find(
      (el) => !!el.closest(".ant-list-item")
    ) as HTMLElement;
    fireEvent.click(firstTitle);
    await waitFor(() => {
      expect(mockGetMessages).toHaveBeenCalledWith(1);
    });
    mockGetMessages.mockClear();

    // Find the delete button on the "first" row
    const firstRow = firstTitle.closest(".ant-list-item") as HTMLElement;
    const trigger = firstRow.querySelector("button") as HTMLButtonElement;
    fireEvent.click(trigger);
    await waitFor(() => {
      expect(screen.getByText("确认删除该对话?")).toBeTruthy();
    });

    const confirmBtn = (await screen.findAllByRole("button", { name: "删除" })).find(
      (btn) => !!btn.closest(".ant-popconfirm")
    ) as HTMLButtonElement;
    fireEvent.click(confirmBtn);

    // After delete, currentConv should jump to the second conv -> getMessages(2)
    await waitFor(() => {
      expect(mockGetMessages).toHaveBeenCalledWith(2);
    });
    // And the "first" row should no longer be in the list
    await waitFor(() => {
      expect(screen.queryByText("first")).toBeNull();
    });
  });
});
