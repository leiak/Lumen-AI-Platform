// frontend/__tests__/wx-publisher/draft-list.test.tsx
// M32 — 公众号助手 — T27 前端测试.
// 草稿列表页 3 个 case: 表格渲染 / 状态过滤 / 搜索.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";

// Hoisted mocks — vitest hoists vi.mock to top of file.
const mockList = vi.fn();
vi.mock("@/services/wx-publisher", () => ({
  draftApi: {
    list: (...args: any[]) => mockList(...args),
  },
}));

// next/navigation 是 client component 必备 — mock 掉 router.
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: (...args: any[]) => mockPush(...args),
    back: vi.fn(),
    refresh: vi.fn(),
  }),
  useParams: () => ({}),
  usePathname: () => "/dashboard/wx-publisher/drafts",
}));

import DraftsPage from "@/app/dashboard/wx-publisher/drafts/page";
import type { WxDraftListItem } from "@/types/wx-publisher";

const sampleDraft = (
  id: number,
  title: string,
  status: WxDraftListItem["status"] = "draft"
): WxDraftListItem => ({
  id,
  title,
  status,
  account_id: null,
  template_id: null,
  updated_at: "2026-06-18T08:00:00Z",
});

describe("DraftsPage", () => {
  beforeEach(() => {
    mockList.mockReset();
    mockPush.mockReset();
  });

  it("renders draft list table with rows from API", async () => {
    mockList.mockResolvedValueOnce({
      items: [sampleDraft(1, "AI Agent 入门"), sampleDraft(2, "RAG 实战")],
      total: 2,
      page: 1,
      page_size: 10,
    });
    render(
      <TestWrapper>
        <DraftsPage />
      </TestWrapper>
    );
    await waitFor(() =>
      expect(screen.getByText("AI Agent 入门")).toBeInTheDocument()
    );
    expect(screen.getByText("RAG 实战")).toBeInTheDocument();
    // 状态 Tag 也应渲染
    expect(screen.getAllByText("草稿").length).toBeGreaterThan(0);
  });

  it("filters by status (草稿/排版中/待发布/已发布/失败) via select", async () => {
    mockList.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 10,
    });
    render(
      <TestWrapper>
        <DraftsPage />
      </TestWrapper>
    );
    // 等列表 query 跑过第一次 (默认 status 过滤未设)
    await waitFor(() => expect(mockList).toHaveBeenCalled());
    const initialCalls = mockList.mock.calls.length;

    // AntD Select 的 placeholder "状态" — 用 querySelector 找到 selector 容器
    // 再 fireEvent.mouseDown 打开下拉 (AntD v5 必走 mousedown 触发).
    const placeholderSpan = Array.from(
      document.querySelectorAll(".ant-select-selection-placeholder")
    ).find((el) => el.textContent === "状态");
    expect(placeholderSpan).toBeDefined();
    const selectorDiv = placeholderSpan!.closest(".ant-select-selector")!;
    fireEvent.mouseDown(selectorDiv);

    await waitFor(() => expect(screen.getByText("已发布")).toBeInTheDocument());
    fireEvent.click(screen.getByText("已发布"));

    // 触发了新的 query, params.status 应是 'published'.
    await waitFor(() =>
      expect(mockList.mock.calls.length).toBeGreaterThan(initialCalls)
    );
    const lastCallArgs = mockList.mock.calls[mockList.mock.calls.length - 1][0];
    expect(lastCallArgs).toMatchObject({ status: "published", page: 1 });
  });

  it("search by title triggers API refetch", async () => {
    mockList.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 10,
    });
    render(
      <TestWrapper>
        <DraftsPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockList).toHaveBeenCalled());
    const initialCalls = mockList.mock.calls.length;

    // 找搜索 Input (placeholder "搜索标题") 然后按 Enter.
    const searchInput = screen.getByPlaceholderText("搜索标题");
    fireEvent.change(searchInput, { target: { value: "AI Agent" } });
    // 触发 handleSearch (onPressEnter).
    fireEvent.keyDown(searchInput, { key: "Enter", code: "Enter" });

    await waitFor(() =>
      expect(mockList.mock.calls.length).toBeGreaterThan(initialCalls)
    );
    const lastCallArgs = mockList.mock.calls[mockList.mock.calls.length - 1][0];
    expect(lastCallArgs).toMatchObject({ search: "AI Agent", page: 1 });
  });
});
