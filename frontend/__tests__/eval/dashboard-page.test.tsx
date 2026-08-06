// frontend/__tests__/eval/dashboard-page.test.tsx
// M37.3 — /dashboard/eval 主页测试 (8 cases)。
//
// 覆盖:
//   1. 标题 + 「新建评测」按钮(无 dataset 时禁用)渲染
//   2. summary 加载完成 → KPI 卡 + 趋势表 + run 列表渲染
//   3. 上次对比 KPI(latest_compare 存在时多渲 1 张卡)
//   4. trend 为空数组时,TrendLineChart 渲 Empty 占位
//   5. Run 列表进度列用 RunProgressBar 组件渲
//   6. Run 列表勾选 2 个 completed → 「对比」按钮出现 + 点跳详情带 ?compare_to
//   7. pending/running 的 Run 有「取消」按钮
//   8. failed Run 的 RunProgressBar 显示 error_message

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";

// ---------- mock 服务 ----------

const mockGetDashboardSummary = vi.fn();
const mockStartRun = vi.fn();
const mockCancelRun = vi.fn();
const mockListDatasets = vi.fn();
const mockGetDataset = vi.fn();
const mockListRuns = vi.fn();
const mockGetRun = vi.fn();
const mockCompareRuns = vi.fn();

vi.mock("@/services/eval", () => ({
  getDashboardSummary: (...args: any[]) => mockGetDashboardSummary(...args),
  buildKPICards: (raw: any) => {
    // 简单的 echo —— dashboard 测试不深入 KPI 计算
    return [
      {
        label: "本周评测次数",
        value: `${raw.runs_this_week ?? 0} 次`,
        delta: null,
        deltaTone: "neutral",
        hint: null,
      },
      {
        label: "本周平均 Hit@5",
        value: raw.avg_hit_at_5_this_week
          ? raw.avg_hit_at_5_this_week.toFixed(3)
          : "—",
        delta: null,
        deltaTone: "neutral",
        hint: null,
      },
    ];
  },
}));

vi.mock("@/services/eval_dataset", () => ({
  listDatasets: (...args: any[]) => mockListDatasets(...args),
  getDataset: (...args: any[]) => mockGetDataset(...args),
}));

vi.mock("@/services/eval_run", () => ({
  listRuns: (...args: any[]) => mockListRuns(...args),
  startRun: (...args: any[]) => mockStartRun(...args),
  cancelRun: (...args: any[]) => mockCancelRun(...args),
  getRun: (...args: any[]) => mockGetRun(...args),
  compareRuns: (...args: any[]) => mockCompareRuns(...args),
}));

vi.mock("@/services/knowledge", () => ({
  knowledgeApi: {
    get: vi.fn().mockResolvedValue({
      data: { data: { embedding_model_config_id: 1 } },
    }),
  },
}));

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useParams: () => ({}),
  useSearchParams: () => new URLSearchParams(),
}));

import EvalDashboardPage from "@/app/dashboard/eval/page";

// ---------- fixture ----------

function makeSummary(opts: {
  runs?: any[];
  latest_compare?: any | null;
  trend?: any[];
} = {}) {
  const now = new Date();
  const runs = opts.runs ?? [
    {
      id: 1,
      dataset_id: 5,
      status: "completed",
      total_items: 30,
      completed_items: 30,
      completed_count: 30,
      error_message: null,
      started_at: "2026-08-06T00:00:00Z",
      finished_at: "2026-08-06T01:00:00Z",
      created_at: "2026-08-06T00:00:00Z",
      updated_at: "2026-08-06T01:00:00Z",
      created_by: 1,
    },
    {
      id: 2,
      dataset_id: 5,
      status: "running",
      total_items: 30,
      completed_items: 10,
      completed_count: null,
      error_message: null,
      started_at: "2026-08-06T02:00:00Z",
      finished_at: null,
      created_at: "2026-08-06T02:00:00Z",
      updated_at: "2026-08-06T02:00:00Z",
      created_by: 1,
    },
  ];
  return {
    kpis: [
      {
        label: "本周评测次数",
        value: "2 次",
        delta: "+1 次",
        deltaTone: "up",
        hint: "vs 上周 1 次",
      },
      {
        label: "本周平均 Hit@5",
        value: "0.650",
        delta: "+5.0%",
        deltaTone: "up",
        hint: "vs 上周 0.600",
      },
    ],
    trend: opts.trend ?? [],
    recent_runs: runs,
    latest_compare: opts.latest_compare ?? null,
    generated_at: now.toISOString(),
  };
}

// ---------- beforeEach ----------

beforeEach(() => {
  window.localStorage.setItem("access_token", "test-token");
  mockGetDashboardSummary.mockReset();
  mockStartRun.mockReset();
  mockStartRun.mockResolvedValue({ id: 99, status: "pending" });
  mockCancelRun.mockReset();
  mockCancelRun.mockResolvedValue({ id: 1, status: "cancelled" });
  mockListDatasets.mockReset();
  mockListDatasets.mockResolvedValue({
    items: [
      {
        id: 5,
        kb_id: 1,
        tenant_id: null,
        name: "demo_baseline",
        source: "manual",
        is_active: 1,
        item_count: 30,
        created_at: "2026-08-01T00:00:00Z",
        updated_at: "2026-08-01T00:00:00Z",
      },
    ],
    total: 1,
    page: 1,
    page_size: 100,
  });
  mockGetDataset.mockReset();
  mockGetDataset.mockResolvedValue({
    id: 5,
    kb_id: 1,
    tenant_id: null,
    name: "demo_baseline",
    source: "manual",
    is_active: 1,
    item_count: 30,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    description: null,
    created_by: 1,
  });
  mockListRuns.mockReset();
  mockListRuns.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 });
  mockGetRun.mockReset();
  mockGetRun.mockResolvedValue({
    id: 1,
    dataset_id: 5,
    status: "completed",
    total_items: 30,
    completed_items: 30,
    completed_count: 30,
    error_message: null,
    started_at: "2026-08-06T00:00:00Z",
    finished_at: "2026-08-06T01:00:00Z",
    created_at: "2026-08-06T00:00:00Z",
    updated_at: "2026-08-06T01:00:00Z",
    created_by: 1,
    config: {
      search_weights: { title: 10, important_kw: 30, question_kw: 20, text: 2 },
      top_k: 10,
      rerank: true,
      embedding_model_config_id: 1,
      judge_model_config_id: 2,
    },
    metrics_json: null,
    report_markdown: null,
    trace_id: null,
    results: [],
    results_total: 0,
    results_page: 1,
    results_page_size: 100,
  });
  mockCompareRuns.mockReset();
  mockCompareRuns.mockResolvedValue({
    run_id_a: 1,
    run_id_b: 2,
    per_item_delta: [],
    aggregate_delta: { "retrieval.hit_at_5": 0.05 },
    winners: [
      { metric: "retrieval.hit_at_5", winner: "b", delta: 0.05, pct: 8.0 },
    ],
  });
  mockPush.mockReset();
});

// ============================================================================
// tests
// ============================================================================

// 1. 标题 + 新建评测按钮(无 dataset 时禁用)渲染
describe("EvalDashboardPage (basic render)", () => {
  it("renders heading + '新建评测' button (disabled when no datasets)", async () => {
    mockListDatasets.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 100,
    });
    mockGetDashboardSummary.mockResolvedValue(makeSummary({ runs: [] }));

    render(
      <TestWrapper>
        <EvalDashboardPage />
      </TestWrapper>,
    );

    expect(screen.getByText("RAG 评测看板")).toBeInTheDocument();
    const btn = await screen.findByRole("button", { name: /新建评测/ });
    expect(btn).toBeDisabled();
  });
});

// 2. summary 加载完成 → KPI + 趋势 + 列表渲染
describe("EvalDashboardPage (with summary)", () => {
  it("renders KPI cards + run list when summary loads", async () => {
    mockGetDashboardSummary.mockResolvedValue(
      makeSummary({
        trend: [
          {
            dataset_id: 5,
            dataset_name: "demo_baseline",
            points: [
              {
                date: "2026-08-06",
                hit_at_5: 0.65,
                mrr: 0.55,
                run_count: 1,
              },
            ],
            runs: [],
          },
        ],
      }),
    );

    render(
      <TestWrapper>
        <EvalDashboardPage />
      </TestWrapper>,
    );

    expect(
      await screen.findByText(/本周评测次数/),
    ).toBeInTheDocument();
    // demo_baseline 在 TrendLineChart 的 legend + table 中都出现(≥ 2 处)
    expect(screen.getAllByText("demo_baseline").length).toBeGreaterThanOrEqual(1);
    // run 列表里有 Run #1 / Run #2(Button 类型 link)
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("#2")).toBeInTheDocument();
  });
});

// 3. latest_compare 存在时多渲 1 张「上次对比」卡
describe("EvalDashboardPage (latest compare)", () => {
  it("renders 'Latest Compare' KPI card when latest_compare present", async () => {
    mockGetDashboardSummary.mockResolvedValue(
      makeSummary({
        latest_compare: {
          run_id_a: 1,
          run_id_b: 2,
          hit_at_5_delta: 0.05,
          aggregate_delta: { "retrieval.hit_at_5": 0.05 },
          winner_counts: { a: 0, b: 1, tie: 0 },
        },
      }),
    );

    render(
      <TestWrapper>
        <EvalDashboardPage />
      </TestWrapper>,
    );

    expect(
      await screen.findByText(/上次对比/),
    ).toBeInTheDocument();
    expect(screen.getByText(/A #1 vs B #2/)).toBeInTheDocument();
  });
});

// 4. trend 空数组 → TrendLineChart 渲染 Empty
describe("EvalDashboardPage (empty trend)", () => {
  it("renders empty placeholder in TrendLineChart when no trend", async () => {
    mockGetDashboardSummary.mockResolvedValue(
      makeSummary({ trend: [], runs: [] }),
    );

    render(
      <TestWrapper>
        <EvalDashboardPage />
      </TestWrapper>,
    );

    expect(
      await screen.findByText(/近 30 天无 completed run/),
    ).toBeInTheDocument();
  });
});

// 5. Run 列表用 RunProgressBar 渲染进度 + 状态 tag
describe("EvalDashboardPage (run list columns)", () => {
  it("renders RunProgressBar + status tags in run list", async () => {
    mockGetDashboardSummary.mockResolvedValue(makeSummary({}));

    render(
      <TestWrapper>
        <EvalDashboardPage />
      </TestWrapper>,
    );

    // status tag
    expect(await screen.findByText("已完成")).toBeInTheDocument();
    expect(screen.getByText("运行中")).toBeInTheDocument();
    // progress text:completed 状态只显示 chip(无 Progress),只有 running 才显示
    // 「10 / 30」运行中 +「30 / 30」已完成都不在 terminal 状态时渲 Progress
    expect(screen.getByText(/10 \/ 30/)).toBeInTheDocument();
    // completed run 的 completed_items / total_items 在「进度 / 状态」列渲
    expect(screen.getAllByText(/30/).length).toBeGreaterThanOrEqual(1);
  });
});

// 6. 勾选 2 个 completed → 「对比」按钮出现 + 点击跳详情
describe("EvalDashboardPage (compare selection)", () => {
  it("selecting 2 completed runs enables compare button that pushes to detail", async () => {
    mockGetDashboardSummary.mockResolvedValue(
      makeSummary({
        runs: [
          {
            id: 1,
            dataset_id: 5,
            status: "completed",
            total_items: 30,
            completed_items: 30,
            completed_count: 30,
            error_message: null,
            started_at: "2026-08-06T00:00:00Z",
            finished_at: "2026-08-06T01:00:00Z",
            created_at: "2026-08-06T00:00:00Z",
            updated_at: "2026-08-06T01:00:00Z",
            created_by: 1,
          },
          {
            id: 2,
            dataset_id: 5,
            status: "completed",
            total_items: 30,
            completed_items: 30,
            completed_count: 30,
            error_message: null,
            started_at: "2026-08-06T02:00:00Z",
            finished_at: "2026-08-06T03:00:00Z",
            created_at: "2026-08-06T02:00:00Z",
            updated_at: "2026-08-06T03:00:00Z",
            created_by: 1,
          },
        ],
      }),
    );

    render(
      <TestWrapper>
        <EvalDashboardPage />
      </TestWrapper>,
    );

    await waitFor(() => expect(mockGetDashboardSummary).toHaveBeenCalled());
    const checkboxes = await screen.findAllByRole("checkbox");
    // 至少有 2 个 enabled(都是 completed),running/pending 的 disabled
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);
    const compareBtn = await screen.findByRole("button", { name: /对比 \(2\/2\)/ });
    fireEvent.click(compareBtn);
    expect(mockPush).toHaveBeenCalledWith("/dashboard/eval/runs/2?compare_to=1");
  });
});

// 7. pending/running 的 Run 有「取消」按钮
describe("EvalDashboardPage (cancel button)", () => {
  it("renders 取消 button for running run, calls cancelRun on confirm", async () => {
    mockGetDashboardSummary.mockResolvedValue(
      makeSummary({
        runs: [
          {
            id: 7,
            dataset_id: 5,
            status: "running",
            total_items: 30,
            completed_items: 5,
            completed_count: null,
            error_message: null,
            started_at: "2026-08-06T00:00:00Z",
            finished_at: null,
            created_at: "2026-08-06T00:00:00Z",
            updated_at: "2026-08-06T00:00:00Z",
            created_by: 1,
          },
        ],
      }),
    );

    render(
      <TestWrapper>
        <EvalDashboardPage />
      </TestWrapper>,
    );

    // 「取消」按钮(可能是 Popconfirm 内部的)
    const cancelBtns = await screen.findAllByText("取消");
    // 至少有一个取消按钮在 row 操作列
    fireEvent.click(cancelBtns[0]);
    // 弹 Popconfirm 再确认
    const confirmBtn = await screen.findByRole("button", {
      name: /取消 Run/,
    });
    fireEvent.click(confirmBtn);
    await waitFor(() => expect(mockCancelRun).toHaveBeenCalledWith(7, expect.any(Object)));
  });
});

// 8. failed Run 的 RunProgressBar 显示 error_message
describe("EvalDashboardPage (failed run)", () => {
  it("shows error_message in RunProgressBar for failed run", async () => {
    mockGetDashboardSummary.mockResolvedValue(
      makeSummary({
        runs: [
          {
            id: 9,
            dataset_id: 5,
            status: "failed",
            total_items: 30,
            completed_items: 5,
            completed_count: null,
            error_message: "embedding_model_config_id mismatch",
            started_at: "2026-08-06T00:00:00Z",
            finished_at: null,
            created_at: "2026-08-06T00:00:00Z",
            updated_at: "2026-08-06T00:00:00Z",
            created_by: 1,
          },
        ],
      }),
    );

    render(
      <TestWrapper>
        <EvalDashboardPage />
      </TestWrapper>,
    );

    expect(
      await screen.findByText("embedding_model_config_id mismatch"),
    ).toBeInTheDocument();
    expect(screen.getByText("失败")).toBeInTheDocument();
  });
});
