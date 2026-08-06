// frontend/__tests__/eval/run-detail.test.tsx
// M37.3 — /dashboard/eval/runs/[id] 详情页测试 (6 cases)。
//
// 覆盖:
//   1. 顶部 info card:status tag / dataset tag / 时间字段
//   2. MetricsRadar 5 维渲染(拿 metrics_json 后)
//   3. 折叠面板「整体指标」statistic 渲染 9 个核心指标
//   4. 「按 Category」折叠面板渲 CategoryBreakdownChart
//   5. FailureList 渲染(从 results 筛失败 case)
//   6. ?compare_to=<id> 时,CompareDelta 区出现 + MetricsRadar 显示 Δ

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { TestWrapper } from "./test-utils";

// ---------- mock 服务 ----------

const mockGetRun = vi.fn();
const mockCompareRuns = vi.fn();
const mockCancelRun = vi.fn();

vi.mock("@/services/eval_run", () => ({
  getRun: (...args: any[]) => mockGetRun(...args),
  compareRuns: (...args: any[]) => mockCompareRuns(...args),
  cancelRun: (...args: any[]) => mockCancelRun(...args),
  startRun: vi.fn(),
  listRuns: vi.fn(),
}));

const mockPush = vi.fn();
const params: Record<string, string> = { id: "1" };
let searchCompareTo: string | null = null;

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useParams: () => params,
  useSearchParams: () => ({
    get: (k: string) => (k === "compare_to" ? searchCompareTo : null),
  }),
}));

import EvalRunDetailPage from "@/app/dashboard/eval/runs/[id]/page";

// ---------- fixture ----------

const FULL_METRICS = {
  retrieval: {
    hit_at_5: 0.65,
    hit_at_10: 0.82,
    mrr: 0.55,
    ndcg_at_10: 0.6,
    recall_at_10: 0.75,
    latency_ms_p50: 120,
    latency_ms_p95: 480,
  },
  answer: {
    keyword_hit_rate: 0.7,
    faithfulness_avg: 1.2,
    answer_relevancy_avg: 1.5,
    llm_judge_total_calls: 60,
  },
  by_category: {
    factual: { hit_at_5: 0.8, mrr: 0.7, count: 10 },
    reasoning: { hit_at_5: 0.5, mrr: 0.4, count: 10 },
    multi_hop: { hit_at_5: 0.6, mrr: 0.5, count: 10 },
  },
  by_difficulty: {
    easy: { hit_at_5: 0.85, mrr: 0.75, count: 10 },
    medium: { hit_at_5: 0.6, mrr: 0.5, count: 10 },
    hard: { hit_at_5: 0.4, mrr: 0.3, count: 10 },
  },
  totals: { items_total: 30, items_success: 28, items_failed: 2 },
};

const SAMPLE_RESULTS = [
  {
    id: 1,
    run_id: 1,
    item_id: 100,
    query: "How to reset password?",
    retrieved_doc_ids: [1, 2, 3],
    retrieval_scores: [0.9, 0.8, 0.7],
    retrieved_contexts: ["To reset password, click on..."],
    answer: "Click on Forgot Password.",
    retrieval_metrics: {
      hit_at_5: 1,
      hit_at_10: 1,
      mrr: 1,
      ndcg_at_10: 1,
      recall_at_10: 1,
    },
    answer_metrics: {
      keyword_hit_rate: 1,
      faithfulness_avg: 2,
      answer_relevancy_avg: 2,
      llm_judge_total_calls: 2,
    },
    llm_judge_calls: null,
    latency_ms: 120,
    error_message: null,
    created_at: "2026-08-06T00:00:00Z",
  },
  {
    id: 2,
    run_id: 1,
    item_id: 101,
    query: "Out of scope question",
    retrieved_doc_ids: [],
    retrieval_scores: [],
    retrieved_contexts: null,
    answer: null,
    retrieval_metrics: {
      hit_at_5: 0, // 检索失败
      hit_at_10: 0,
      mrr: 0,
      ndcg_at_10: 0,
      recall_at_10: 0,
    },
    answer_metrics: null,
    llm_judge_calls: null,
    latency_ms: 80,
    error_message: null,
    created_at: "2026-08-06T00:00:01Z",
  },
];

function makeRun(overrides: Partial<any> = {}) {
  return {
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
    metrics_json: FULL_METRICS,
    report_markdown:
      "# Run Report\n\n## By Category\n- factual: hit_at_5=0.8",
    trace_id: "trace-abc-123",
    results: SAMPLE_RESULTS,
    results_total: 2,
    results_page: 1,
    results_page_size: 100,
    ...overrides,
  };
}

beforeEach(() => {
  window.localStorage.setItem("access_token", "test-token");
  params.id = "1";
  searchCompareTo = null;
  mockGetRun.mockReset();
  mockGetRun.mockResolvedValue(makeRun());
  mockCompareRuns.mockReset();
  mockCompareRuns.mockResolvedValue({
    run_id_a: 5,
    run_id_b: 1,
    per_item_delta: [],
    aggregate_delta: { "retrieval.hit_at_5": 0.05 },
    winners: [
      { metric: "retrieval.hit_at_5", winner: "b", delta: 0.05, pct: 8.0 },
    ],
  });
  mockCancelRun.mockReset();
  mockCancelRun.mockResolvedValue({ id: 1, status: "cancelled" });
  mockPush.mockReset();
});

// ============================================================================
// tests
// ============================================================================

// 1. info card:status tag / dataset / 时间字段
describe("EvalRunDetailPage (info card)", () => {
  it("renders info card with status tag, dataset id, timestamps, trace id", async () => {
    render(
      <TestWrapper>
        <EvalRunDetailPage />
      </TestWrapper>,
    );
    // 等 metrics 加载完成,会渲 MetricsRadar(检索指标)
    expect(
      await screen.findByText("检索指标 / Retrieval Metrics"),
    ).toBeInTheDocument();
    // status tag
    expect(screen.getByText("已完成")).toBeInTheDocument();
    // dataset
    expect(screen.getAllByText("#5").length).toBeGreaterThanOrEqual(1);
    // trace id
    expect(screen.getByText("trace-abc-123")).toBeInTheDocument();
  });
});

// 2. MetricsRadar 5 维渲染
describe("EvalRunDetailPage (metrics radar)", () => {
  it("renders all 5 retrieval metric labels", async () => {
    render(
      <TestWrapper>
        <EvalRunDetailPage />
      </TestWrapper>,
    );
    expect(
      await screen.findByText("检索指标 / Retrieval Metrics"),
    ).toBeInTheDocument();
    // MetricsRadar + 整体指标 panel 都含 Hit@5,多个匹配
    expect(screen.getAllByText("Hit@5").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("Hit@10").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("MRR").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("NDCG@10").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("Recall@10").length).toBeGreaterThanOrEqual(2);
  });
});

// 3. 「整体指标」折叠面板渲 9 个核心 statistic
describe("EvalRunDetailPage (overall metrics panel)", () => {
  it("renders 9 overall metric statistics", async () => {
    render(
      <TestWrapper>
        <EvalRunDetailPage />
      </TestWrapper>,
    );
    // 等页面渲染完成(找 MetricsRadar 标题)
    await screen.findByText("检索指标 / Retrieval Metrics");
    // MetricsRadar + 整体指标 panel 都含 Hit@5,多个匹配
    expect(screen.getAllByText("Hit@5").length).toBeGreaterThanOrEqual(2);
    // Faithfulness avg title
    expect(screen.getByText("Faithfulness avg")).toBeInTheDocument();
    expect(screen.getByText("Answer Relevancy avg")).toBeInTheDocument();
    // Keyword Hit Rate —— 显示 70.0%
    expect(screen.getByText(/70\.0%/)).toBeInTheDocument();
    // Judge 调用总数
    expect(screen.getByText("60")).toBeInTheDocument();
  });
});

// 4. 「按 Category」折叠面板渲 CategoryBreakdownChart(点开后才渲内容 —— 这里点开)
describe("EvalRunDetailPage (by category breakdown)", () => {
  it("renders by_category breakdown when accordion expanded", async () => {
    render(
      <TestWrapper>
        <EvalRunDetailPage />
      </TestWrapper>,
    );
    await waitFor(() => expect(mockGetRun).toHaveBeenCalled());
    // 点开 by_category 折叠
    const categoryHeader = await screen.findByText("按 Category / By Category");
    categoryHeader.click();
    // 等待渲 by_category table 行
    expect(await screen.findByText("factual")).toBeInTheDocument();
    expect(screen.getByText("reasoning")).toBeInTheDocument();
    expect(screen.getByText("multi_hop")).toBeInTheDocument();
  });
});

// 5. FailureList 渲染(从 results 筛失败 case)
describe("EvalRunDetailPage (failure list)", () => {
  it("renders failures with reasons extracted from results", async () => {
    render(
      <TestWrapper>
        <EvalRunDetailPage />
      </TestWrapper>,
    );
    await waitFor(() => expect(mockGetRun).toHaveBeenCalled());
    expect(await screen.findByText("失败 Cases / Failures")).toBeInTheDocument();
    // 至少 1 条失败 —— retrieval hit_at_5=0 + answer_metrics=null
    expect(screen.getByText(/检索全 miss/)).toBeInTheDocument();
    // 「1 失败」tag
    expect(screen.getByText("1 失败")).toBeInTheDocument();
  });
});

// 6. ?compare_to=<id> 时,CompareDelta 出现 + MetricsRadar 显示 Δ
describe("EvalRunDetailPage (compare via ?compare_to)", () => {
  it("renders CompareDelta + Δ row in MetricsRadar when compare_to query set", async () => {
    params.id = "2";
    searchCompareTo = "1";

    // 当前 run = #2,baseline = #1
    mockGetRun.mockImplementation(async (id: number) => {
      if (id === 1) return makeRun({ id: 1 });
      return makeRun({ id: 2, dataset_id: 5 });
    });

    render(
      <TestWrapper>
        <EvalRunDetailPage />
      </TestWrapper>,
    );

    // 等 baseline 标题里出现 "vs Run #1"
    await screen.findByText(/vs Run #1/);
    // CompareDelta 标题 card
    expect(
      screen.getByText(/对比 Run #1 → Run #2/),
    ).toBeInTheDocument();
    // CompareDelta 表格里有 winner label "B 胜"(也可能在 MetricsRadar 里出现)
    // 这里只检查 Δ 行(MetricsRadar baseline 对比渲 5 个 Δ 行)
    expect(screen.getAllByText(/Δ /).length).toBeGreaterThanOrEqual(5);
  });
});
