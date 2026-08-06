"use client";

// frontend/components/eval/CompareDelta.tsx
// M37.2 — 两 run 对比视图(aggregate 维度)。
//
// 表格列:metric / a(基线)/ b(新)/ delta / winner 标签。
//
// 数据走 EvalRunCompareResponse:
//   - aggregate_delta: { "retrieval.hit_at_5": 0.06, ... }
//   - winners: [{ metric, winner, delta, pct }, ...]
//
// 渲染策略:从 winners list 拿出 metric / winner,从 aggregate_delta 拿 a/b
// 数值,通过 spec §4.2 fixed list 拿基线值(0.0 fallback,因为 compare 端不
// 直接返回 a/b 列 —— aggregate_delta 只有 delta,不返 a / b 绝对值)。

import { Table, Tag, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { EvalRunCompareResponse } from "@/types/eval_run";

interface CompareDeltaProps {
  compare: EvalRunCompareResponse;
}

interface Row {
  metric: string;
  delta: number;
  winner: "a" | "b" | "tie";
  pct: number | null;
}

const WINNER_LABEL: Record<Row["winner"], string> = {
  a: "A 胜 / A wins",
  b: "B 胜 / B wins",
  tie: "平 / Tie",
};

const WINNER_COLOR: Record<Row["winner"], string> = {
  a: "orange",
  b: "green",
  tie: "default",
};

function formatMetric(metric: string): string {
  // spec format: "retrieval.hit_at_5" → "Retrieval · Hit@5"
  const [section, key] = metric.split(".", 2);
  if (!section || !key) return metric;
  // 重命名 key:hit_at_5 → Hit@5、latency_ms_p50 → Latency p50
  const pretty = key
    .replace(/_at_(\d+)/, "@$1")
    .replace(/_avg$/, " avg")
    .replace(/_ms_p(\d+)/, " p$1 (ms)")
    .replace(/_/g, " ");
  return `${section[0].toUpperCase() + section.slice(1)} · ${pretty}`;
}

export default function CompareDelta({ compare }: CompareDeltaProps) {
  const rows: Row[] = compare.winners.map((w) => ({
    metric: w.metric,
    delta: w.delta,
    winner: w.winner,
    pct: w.pct ?? null,
  }));

  const columns: ColumnsType<Row> = [
    {
      title: "Metric",
      dataIndex: "metric",
      key: "metric",
      render: (m: string) => formatMetric(m),
    },
    {
      title: "Delta (B - A)",
      dataIndex: "delta",
      key: "delta",
      render: (d: number) => {
        const arrow = d > 0 ? "↑" : d < 0 ? "↓" : "→";
        const color = d > 0 ? "#3f8600" : d < 0 ? "#cf1322" : "#999";
        return (
          <span style={{ color, fontWeight: 500 }}>
            {arrow} {d.toFixed(4)}
          </span>
        );
      },
    },
    {
      title: "Pct",
      dataIndex: "pct",
      key: "pct",
      render: (pct: number | null) =>
        pct === null || pct === undefined ? "—" : `${pct.toFixed(1)}%`,
    },
    {
      title: "Winner",
      dataIndex: "winner",
      key: "winner",
      render: (w: Row["winner"]) => (
        <Tooltip title={WINNER_LABEL[w]}>
          <Tag color={WINNER_COLOR[w]}>{WINNER_LABEL[w]}</Tag>
        </Tooltip>
      ),
    },
  ];

  return (
    <Table<Row>
      columns={columns}
      dataSource={rows}
      rowKey="metric"
      size="small"
      pagination={false}
      bordered
    />
  );
}
