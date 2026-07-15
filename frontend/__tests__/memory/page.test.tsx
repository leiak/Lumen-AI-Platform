// frontend/__tests__/memory/page.test.tsx
// Page-level tests for /dashboard/memory: the M15 "global context
// distinguishes current conv from others" feature. Pins down:
//   1. Default "all" view shows every row; selecting a conv dims the
//      rows from that conv (opacity 0.45) but leaves other convs +
//      legacy NULL-conv rows at full opacity.
//   2. Toggling to "只看其它会话" filters out the selected conv's rows
//      (other convs + legacy NULL-conv rows stay visible).
//   3. No conv selected → no dimming; default toggle is "全部" and the
//      "全部" segment is the active one in AntD's Segmented.
//
// Reference: page-agent-binding.test.tsx for the TestWrapper / mock
// pattern. The MemoryPage does NOT use App.useApp() directly (it uses
// the static `message.error` API), so the <App> wrapper is here for
// parity with sibling tests; future refactors may move to App.useApp()
// per MEMORY.md's "antd v5 toast 不显示" lesson.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { App, ConfigProvider } from "antd";

const mockListConversations = vi.fn();
const mockGetGlobalContext = vi.fn();
const mockGetHistory = vi.fn();

vi.mock("@/services/chat", () => ({
  chatApi: {
    listConversations: (...args: any[]) => mockListConversations(...args),
  },
}));
vi.mock("@/services/memory", () => ({
  memoryApi: {
    getGlobalContext: (...args: any[]) => mockGetGlobalContext(...args),
    getHistory: (...args: any[]) => mockGetHistory(...args),
    searchMemory: vi.fn(),
    clearMemory: vi.fn(),
  },
}));

import MemoryPage from "@/app/dashboard/memory/page";
import type { Conversation } from "@/types/chat";
import type { MemoryMessage } from "@/services/memory";

const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>
    <App>{children}</App>
  </ConfigProvider>
);

const FAKE_CONVS: Conversation[] = [
  { id: 42, title: "我是问模型", created_at: "2026-06-09T10:00:00Z", updated_at: "2026-06-09T10:00:00Z" },
  { id: 99, title: "另一会话",    created_at: "2026-06-09T09:00:00Z", updated_at: "2026-06-09T09:00:00Z" },
];

const FAKE_GLOBAL: MemoryMessage[] = [
  { role: "user",      content: "来自会话 42",  metadata: {}, conversation_id: 42 },
  { role: "assistant", content: "回复会话 42",  metadata: {}, conversation_id: 42 },
  { role: "user",      content: "来自会话 99",  metadata: {}, conversation_id: 99 },
  { role: "user",      content: "legacy no conv", metadata: {}, conversation_id: null },
];

const listRes = (list: Conversation[]) => ({
  data: { code: 200, message: "ok", data: list },
});
const globalRes = (rows: MemoryMessage[]) => ({
  data: { code: 200, message: "ok", data: rows },
});
const emptyList = () => ({ data: { code: 200, message: "ok", data: [] } });

beforeEach(() => {
  vi.clearAllMocks();
  mockListConversations.mockResolvedValue(listRes(FAKE_CONVS));
  mockGetGlobalContext.mockResolvedValue(globalRes(FAKE_GLOBAL));
  mockGetHistory.mockResolvedValue(emptyList());
});

describe("MemoryPage — M15 global context current-conv distinguish", () => {
  it("默认全部可见,选中会话后该会话条目淡显 (opacity 0.45)", async () => {
    render(<MemoryPage />, { wrapper: TestWrapper });

    // 等全局上下文渲染完
    await waitFor(() => {
      expect(screen.getByText("来自会话 42")).toBeInTheDocument();
    });
    expect(screen.getByText("来自会话 99")).toBeInTheDocument();
    expect(screen.getByText("legacy no conv")).toBeInTheDocument();

    // 选 42 号会话(用 fireEvent 同步触发,避免 userEvent 在全套
    // vitest run 里的 act() 警告链路)
    const conv42 = await screen.findByText("我是问模型");
    fireEvent.click(conv42);

    // 来自会话 42 的条目应该淡显 (opacity 0.45)
    const item42 = screen.getByText("来自会话 42").closest("li");
    expect(item42).toBeTruthy();
    expect((item42 as HTMLElement).style.opacity).toBe("0.45");

    // 来自会话 99 的不淡显
    const item99 = screen.getByText("来自会话 99").closest("li");
    expect(item99).toBeTruthy();
    expect((item99 as HTMLElement).style.opacity).not.toBe("0.45");

    // legacy (conversation_id=null) 不淡显 — 我们不知道它来自哪个 conv
    const itemLegacy = screen.getByText("legacy no conv").closest("li");
    expect(itemLegacy).toBeTruthy();
    expect((itemLegacy as HTMLElement).style.opacity).not.toBe("0.45");
  });

  it("切换到「只看其它会话」,当前会话条目被过滤掉", async () => {
    render(<MemoryPage />, { wrapper: TestWrapper });

    await waitFor(() => {
      expect(screen.getByText("来自会话 42")).toBeInTheDocument();
    });

    // 选 42 号会话
    fireEvent.click(await screen.findByText("我是问模型"));

    // 切到「只看其它会话」
    const toggle = screen.getByText("只看其它会话");
    fireEvent.click(toggle);

    // 来自 42 的两条都不见了,99 和 legacy 还在
    await waitFor(() => {
      expect(screen.queryByText("来自会话 42")).not.toBeInTheDocument();
    });
    expect(screen.queryByText("回复会话 42")).not.toBeInTheDocument();
    expect(screen.getByText("来自会话 99")).toBeInTheDocument();
    expect(screen.getByText("legacy no conv")).toBeInTheDocument();
  });

  it("未选中会话时,所有条目都不淡显,默认 toggle 是「全部」", async () => {
    render(<MemoryPage />, { wrapper: TestWrapper });

    await waitFor(() => {
      expect(screen.getByText("来自会话 42")).toBeInTheDocument();
    });

    // 没选 conv,所以都不淡显
    const item42 = screen.getByText("来自会话 42").closest("li");
    expect(item42).toBeTruthy();
    expect((item42 as HTMLElement).style.opacity).not.toBe("0.45");
    const item99 = screen.getByText("来自会话 99").closest("li");
    expect(item99).toBeTruthy();
    expect((item99 as HTMLElement).style.opacity).not.toBe("0.45");

    // AntD Segmented 给 active option 加 ant-segmented-item-selected
    const allBtn = screen.getByText("全部");
    expect(allBtn.closest(".ant-segmented-item-selected")).toBeTruthy();
  });
});
