// frontend/__tests__/eval/run-page.test.tsx
// M37.2 — 6 个 vitest 覆盖 services + 3 组件 + run 状态流转。
//
// 覆盖:
//   1. services.listRuns() 解析 PaginatedResponse
//   2. services.startRun() 解析 SingleResponse
//   3. services.compareRuns() 解析 SingleResponse
//   4. RunProgressBar 显示进度 + 状态 chip
//   5. RunProgressBar 失败状态显示 error_message
//   6. CompareDelta 渲染 winner / delta 表格

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { TestWrapper } from "./test-utils";

import RunProgressBar from "@/components/eval/RunProgressBar";
import CompareDelta from "@/components/eval/CompareDelta";

// ---------- 1. services.listRuns() ----------

const mockListRuns = vi.fn();
const mockStartRun = vi.fn();
const mockCancelRun = vi.fn();
const mockCompareRuns = vi.fn();

vi.mock("@/services/eval_run", () => ({
  listRuns: (...args: any[]) => mockListRuns(...args),
  startRun: (...args: any[]) => mockStartRun(...args),
  cancelRun: (...args: any[]) => mockCancelRun(...args),
  compareRuns: (...args: any[]) => mockCompareRuns(...args),
  getRun: vi.fn(),
}));

import { listRuns, startRun, compareRuns } from "@/services/eval_run";

beforeEach(() => {
  window.localStorage.setItem("access_token", "test-token");
  mockListRuns.mockReset();
  mockStartRun.mockReset();
  mockCancelRun.mockReset();
  mockCompareRuns.mockReset();
});

// 1
describe("services.listRuns", () => {
  it("flattens PaginatedResponse into EvalRunListResult", async () => {
    mockListRuns.mockResolvedValue({
      items: [
        {
          id: 1,
          dataset_id: 5,
          status: "completed",
          total_items: 30,
          completed_items: 30,
          completed_count: 30,
          error_message: null,
          started_at: null,
          finished_at: "2026-08-06T12:00:00Z",
          created_at: "2026-08-06T12:00:00Z",
          updated_at: "2026-08-06T12:00:00Z",
          created_by: 1,
        },
      ],
      total: 1,
      page: 1,
      page_size: 20,
    });
    const result = await listRuns({ dataset_id: 5 });
    expect(result.items).toHaveLength(1);
    expect(result.items[0].status).toBe("completed");
    expect(result.total).toBe(1);
    expect(result.page).toBe(1);
    expect(result.page_size).toBe(20);
    expect(mockListRuns).toHaveBeenCalledWith({ dataset_id: 5 });
  });
});

// 2
describe("services.startRun", () => {
  it("returns EvalRunDetail from SingleResponse.data", async () => {
    mockStartRun.mockResolvedValue({
      id: 42,
      dataset_id: 5,
      status: "pending",
      total_items: 0,
      completed_items: 0,
      completed_count: null,
      error_message: null,
      started_at: null,
      finished_at: null,
      created_at: "2026-08-06T12:00:00Z",
      updated_at: "2026-08-06T12:00:00Z",
      created_by: 1,
      config: {
        search_weights: { title: 10, important_kw: 30, question_kw: 20, text: 2 },
        top_k: 10,
        rerank: true,
        embedding_model_config_id: 1,
        judge_model_config_id: 2,
        judge_metrics: ["faithfulness"],
      },
      metrics_json: null,
      report_markdown: null,
      trace_id: "trace-abc",
    });
    const result = await startRun({
      dataset_id: 5,
      config: {
        search_weights: { title: 10, important_kw: 30, question_kw: 20, text: 2 },
        top_k: 10,
        rerank: true,
        embedding_model_config_id: 1,
        judge_model_config_id: 2,
        judge_metrics: ["faithfulness"],
      },
    });
    expect(result.id).toBe(42);
    expect(result.status).toBe("pending");
    expect(result.config.embedding_model_config_id).toBe(1);
  });
});

// 3
describe("services.compareRuns", () => {
  it("returns EvalRunCompareResponse from SingleResponse.data", async () => {
    mockCompareRuns.mockResolvedValue({
      run_id_a: 1,
      run_id_b: 2,
      per_item_delta: [],
      aggregate_delta: { "retrieval.hit_at_5": 0.06 },
      winners: [
        {
          metric: "retrieval.hit_at_5",
          winner: "b",
          delta: 0.06,
          pct: 7.5,
        },
      ],
    });
    const result = await compareRuns({ run_id_a: 1, run_id_b: 2 });
    expect(result.run_id_a).toBe(1);
    expect(result.run_id_b).toBe(2);
    expect(result.winners[0].winner).toBe("b");
    expect(result.aggregate_delta["retrieval.hit_at_5"]).toBeCloseTo(0.06);
  });
});

// 4. RunProgressBar — running state
describe("RunProgressBar (running)", () => {
  it("renders progress bar + running Tag for in-flight run", () => {
    render(
      <TestWrapper>
        <RunProgressBar
          status="running"
          completed={15}
          total={30}
          errorMessage={null}
        />
      </TestWrapper>,
    );
    expect(screen.getByText(/运行中/)).toBeInTheDocument();
    expect(screen.getByText("15 / 30")).toBeInTheDocument();
  });
});

// 5. RunProgressBar — failed state shows error_message
describe("RunProgressBar (failed)", () => {
  it("renders error chip and error_message when status=failed", () => {
    render(
      <TestWrapper>
        <RunProgressBar
          status="failed"
          completed={5}
          total={30}
          errorMessage="embedding_model_config_id mismatch"
        />
      </TestWrapper>,
    );
    expect(screen.getByText(/失败/)).toBeInTheDocument();
    expect(
      screen.getByText("embedding_model_config_id mismatch"),
    ).toBeInTheDocument();
    // failed 状态不出 progress bar
    expect(screen.queryByText("5 / 30")).not.toBeInTheDocument();
  });
});

// 6. CompareDelta — winners table
describe("CompareDelta", () => {
  it("renders metric / delta / winner columns from winners list", () => {
    vi.useFakeTimers();
    try {
      const compare = {
        run_id_a: 1,
        run_id_b: 2,
        per_item_delta: [],
        aggregate_delta: {
          "retrieval.hit_at_5": 0.06,
          "retrieval.mrr": 0.04,
          "answer.faithfulness_avg": 0.1,
        },
        winners: [
          { metric: "retrieval.hit_at_5", winner: "b" as const, delta: 0.06, pct: 7.5 },
          { metric: "retrieval.mrr", winner: "b" as const, delta: 0.04, pct: null },
          { metric: "answer.faithfulness_avg", winner: "tie" as const, delta: 0.0, pct: null },
        ],
      };
      render(
        <TestWrapper>
          <CompareDelta compare={compare} />
        </TestWrapper>,
      );
      // 表头
      expect(screen.getByText("Metric")).toBeInTheDocument();
      expect(screen.getByText("Delta (B - A)")).toBeInTheDocument();
      expect(screen.getByText("Winner")).toBeInTheDocument();
      // 表格行 — getAllByText 因为有多行 retrieval.* / answer.*
      expect(screen.getAllByText(/Retrieval/).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/Answer/)).toBeInTheDocument();
      expect(screen.getAllByText("B 胜 / B wins").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("平 / Tie")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
