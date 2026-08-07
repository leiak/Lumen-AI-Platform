// frontend/__tests__/eval/runs-list.test.tsx
// M37.3 — /dashboard/eval/runs list page tests (4 cases)。
//
// 配合侧边栏菜单 M37.3 改造一起 ship —— 新增「评测运行」二级菜单 + 完整
// runs 列表页(看板里的 run table 是简化版,这里才是全量管理界面)。
//
// 覆盖:
//   1. 空列表渲染 Empty + 「返回看板」「刷新」按钮 + filter bar
//   2. 有数据时表格行:id link → /dashboard/eval/runs/{id}、dataset Tag、状态 Tag、进度百分比
//   3. status filter 改变触发 listRuns 重调用(带 status 参数)
//   4. 点「详情」按钮调 router.push 到详情页

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";

const mockListRuns = vi.fn();
const mockCancelRun = vi.fn();

vi.mock("@/services/eval_run", () => ({
  listRuns: (...args: any[]) => mockListRuns(...args),
  cancelRun: (...args: any[]) => mockCancelRun(...args),
  startRun: vi.fn(),
  compareRuns: vi.fn(),
  getRun: vi.fn(),
}));

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

import EvalRunsPage from "@/app/dashboard/eval/runs/page";

beforeEach(() => {
  window.localStorage.setItem("access_token", "test-token");
  mockListRuns.mockReset();
  mockListRuns.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 });
  mockCancelRun.mockReset();
  mockCancelRun.mockResolvedValue({ id: 0 });
  mockPush.mockReset();
});

describe("EvalRunsPage", () => {
  it("renders heading + filter bar + Empty when list is empty", async () => {
    render(
      <TestWrapper>
        <EvalRunsPage />
      </TestWrapper>,
    );
    expect(screen.getByText("评测运行")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /返回看板/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /刷新/ })).toBeInTheDocument();
    await waitFor(() => expect(mockListRuns).toHaveBeenCalled());
    expect(
      await screen.findByText(/还没有 run,从「评测数据集」挑一个 dataset 启动/),
    ).toBeInTheDocument();
  });

  it("renders rows with status Tag + progress text + clickable #id link", async () => {
    mockListRuns.mockResolvedValue({
      items: [
        {
          id: 42,
          dataset_id: 57,
          status: "completed",
          total_items: 30,
          completed_items: 30,
          completed_count: 30,
          error_message: null,
          started_at: "2026-08-07T03:00:00Z",
          finished_at: "2026-08-07T03:01:30Z",
          created_at: "2026-08-07T03:00:00Z",
          updated_at: "2026-08-07T03:01:30Z",
          created_by: 1,
        },
        {
          id: 43,
          dataset_id: 57,
          status: "running",
          total_items: 30,
          completed_items: 10,
          completed_count: 10,
          error_message: null,
          started_at: "2026-08-07T03:05:00Z",
          finished_at: null,
          created_at: "2026-08-07T03:05:00Z",
          updated_at: "2026-08-07T03:06:00Z",
          created_by: 1,
        },
      ],
      total: 2,
      page: 1,
      page_size: 100,
    });
    render(
      <TestWrapper>
        <EvalRunsPage />
      </TestWrapper>,
    );
    await waitFor(() => expect(mockListRuns).toHaveBeenCalled());
    // 状态 tag
    expect(await screen.findByText("已完成")).toBeInTheDocument();
    expect(screen.getByText("运行中")).toBeInTheDocument();
    // 进度百分比 — 30/30 → 100%,10/30 → 33%
    expect(screen.getByText(/100%/)).toBeInTheDocument();
    expect(screen.getByText(/33%/)).toBeInTheDocument();
    // 详情按钮 — 列表里有 2 行就有 2 个「详情」按钮
    const detailsBtns = screen.getAllByRole("button", { name: /详情/ });
    expect(detailsBtns.length).toBe(2);
    // dataset tag 显示为 #57
    expect(screen.getAllByText("#57").length).toBeGreaterThan(0);
  });

  it("clicking #id link navigates to run detail page", async () => {
    mockListRuns.mockResolvedValue({
      items: [
        {
          id: 99,
          dataset_id: 5,
          status: "completed",
          total_items: 10,
          completed_items: 10,
          completed_count: 10,
          error_message: null,
          started_at: null,
          finished_at: "2026-08-07T03:00:00Z",
          created_at: "2026-08-07T03:00:00Z",
          updated_at: "2026-08-07T03:00:00Z",
          created_by: 1,
        },
      ],
      total: 1,
      page: 1,
      page_size: 100,
    });
    render(
      <TestWrapper>
        <EvalRunsPage />
      </TestWrapper>,
    );
    await waitFor(() => expect(mockListRuns).toHaveBeenCalled());
    fireEvent.click(await screen.findByRole("button", { name: /^#99$/ }));
    expect(mockPush).toHaveBeenCalledWith("/dashboard/eval/runs/99");
  });

  it("status filter change triggers refetch with new status param", async () => {
    render(
      <TestWrapper>
        <EvalRunsPage />
      </TestWrapper>,
    );
    await waitFor(() => expect(mockListRuns).toHaveBeenCalledTimes(1));
    // 打开 status Select 下拉(M37 看板同样模式是 placeholder 触发的)
    const selects = screen.getAllByRole("combobox");
    // 第一个 combobox 应该是 status Select
    fireEvent.mouseDown(selects[0]);
    // 选「已完成」
    const completedOpt = await screen.findByText("已完成");
    fireEvent.click(completedOpt);
    await waitFor(() => expect(mockListRuns).toHaveBeenCalledTimes(2));
    // 第二次调用应该带 status: 'completed'
    const lastCall = mockListRuns.mock.calls[mockListRuns.mock.calls.length - 1][0];
    expect(lastCall).toMatchObject({ status: "completed" });
  });
});
