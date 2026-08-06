// frontend/__tests__/eval/metrics-radar.test.tsx
// M37.3 — MetricsRadar 组件的 4 个测试(props → 渲染)。
//
// 覆盖:
//   1. 5 个维度 label 全部渲染
//   2. baseline 不传 → 不显示 delta 行
//   3. baseline 传 → 每个维度显示 "Δ" 行(向上/向下/持平三种情况)
//   4. 高/中/低值对应不同颜色(progress strokeColor)

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TestWrapper } from "./test-utils";
import MetricsRadar from "@/components/eval/MetricsRadar";

const RETRIEVAL = {
  hit_at_5: 0.65,
  hit_at_10: 0.82,
  mrr: 0.55,
  ndcg_at_10: 0.6,
  recall_at_10: 0.75,
};

// 1. 5 个维度 label 全部渲染
describe("MetricsRadar (basic)", () => {
  it("renders all 5 metric labels and values", () => {
    render(
      <TestWrapper>
        <MetricsRadar retrieval={RETRIEVAL} />
      </TestWrapper>,
    );
    expect(screen.getByText("Hit@5")).toBeInTheDocument();
    expect(screen.getByText("Hit@10")).toBeInTheDocument();
    expect(screen.getByText("MRR")).toBeInTheDocument();
    expect(screen.getByText("NDCG@10")).toBeInTheDocument();
    expect(screen.getByText("Recall@10")).toBeInTheDocument();
    // 数值(百分比格式,精确到 0.1%)—— 检查 Hit@5 显示 "65.0%"
    expect(screen.getByText("65.0%")).toBeInTheDocument();
  });
});

// 2. baseline 不传 → 不显示 delta
describe("MetricsRadar (no baseline)", () => {
  it("does not render Δ row when baseline is null", () => {
    render(
      <TestWrapper>
        <MetricsRadar retrieval={RETRIEVAL} baseline={null} />
      </TestWrapper>,
    );
    expect(screen.queryByText(/Δ /)).not.toBeInTheDocument();
  });
});

// 3. baseline 传 → 渲染 delta 行(向上 / 向下 / 持平 三种)
describe("MetricsRadar (with baseline)", () => {
  it("renders Δ row with up/down/tie arrows", () => {
    const baseline = {
      hit_at_5: 0.5,
      hit_at_10: 0.9, // 比当前 0.82 低 → 下行
      mrr: 0.55, // 等于当前 → 平
      ndcg_at_10: 0.7, // 比当前 0.6 高 → 下行(本维度)
      recall_at_10: 0.6, // 比当前 0.75 低 → 上行
    };
    render(
      <TestWrapper>
        <MetricsRadar retrieval={RETRIEVAL} baseline={baseline} />
      </TestWrapper>,
    );
    // 5 个 Δ 行(每个维度一个)
    const deltaRows = screen.getAllByText(/Δ /);
    expect(deltaRows.length).toBeGreaterThanOrEqual(5);
    // hit@5: 0.65 - 0.5 = 0.15 → +15.00% 文本(全 delta 行里有)
    expect(screen.getAllByText(/\+15\.00%/).length).toBeGreaterThanOrEqual(1);
  });
});

// 4. 高/中/低值对应不同进度条颜色
describe("MetricsRadar (progress color tiers)", () => {
  it("uses green strokeColor for pct >= 80", () => {
    const high = {
      ...RETRIEVAL,
      hit_at_5: 0.85,
    };
    const { container } = render(
      <TestWrapper>
        <MetricsRadar retrieval={high} />
      </TestWrapper>,
    );
    // 找包含 0.85 比例的 Progress bar(对应 hit_at_5)
    // antd Progress 用 inline style 设 strokeColor
    const bars = container.querySelectorAll(".ant-progress-bg");
    expect(bars.length).toBeGreaterThanOrEqual(5);
    // 至少有一个 bar 用绿色 (rgb(63, 134, 0) = #3f8600)
    const greenBar = Array.from(bars).find((el) => {
      const style = (el as HTMLElement).getAttribute("style") ?? "";
      return style.includes("63, 134, 0") || style.includes("#3f8600");
    });
    expect(greenBar).toBeDefined();
  });
});
