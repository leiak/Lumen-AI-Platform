"use client";

// frontend/components/eval/RunCompareTable.tsx
// M37.3 — 两 run 对比表(aggregate 维度的可读版)。
//
// CompareDelta 已经做了 aggregate 维度的 metric/winner 表格(plan T16,
// 已 ship),本组件做「并排 + delta」三栏对照版:A baseline / B 新 / Delta。
//
// 入参:`compare` EvalRunCompareResponse + `run_a_name` / `run_b_name`
// (从 EvalRunDetail 拿)。如果任一 run 拿不到名,fall back 到 "Run #{id}"。

import { Card, Empty, Statistic, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { EvalRunCompareResponse } from "@/types/eval_run";

export interface RunCompareTableProps {
  compare: EvalRunCompareResponse;
  /** A baseline run 名(label)。 */
  run_a_name: string;
  /** B 新 run 名(label)。 */
  run_b_name: string;
}

interface Row {
  metric: string;
  delta: number;
  winner: "a" | "b" | "tie";
  pct: number | null;
  /** 用于 SortableColumn 比较:从 aggregate_delta 字典拿不到 a / b 绝对值,只用 delta。 */
  sort_key: number;
}

function formatMetric(metric: string): string {
  const [section, key] = metric.split(".", 2);
  if (!section || !key) return metric;
  const pretty = key
    .replace(/_at_(\d+)/, "@$1")
    .replace(/_avg$/, " avg")
    .replace(/_ms_p(\d+)/, " p$1 (ms)")
    .replace(/_/g, " ");
  return `${section[0].toUpperCase() + section.slice(1)} · ${pretty}`;
}

const WINNER_COLOR: Record<Row["winner"], string> = {
  a: "orange",
  b: "green",
  tie: "default",
};

const WINNER_LABEL: Record<Row["winner"], string> = {
  a: "A 胜 / A wins",
  b: "B 胜 / B wins",
  tie: "平 / Tie",
};

export default function RunCompareTable({
  compare,
  run_a_name,
  run_b_name,
}: RunCompareTableProps) {
  if (!compare.winners || compare.winners.length === 0) {
    return (
      <Card title="Run 对比 / Compare" size="small">
        <Empty description="无可对比指标(可能两次评测都未完成)" />
      </Card>
    );
  }

  const rows: Row[] = compare.winners.map((w) => ({
    metric: w.metric,
    delta: w.delta,
    winner: w.winner,
    pct: w.pct ?? null,
    sort_key: Math.abs(w.delta),
  }));

  // 顶部 KPI 三连:A wins / Tie / B wins
  let winA = 0;
  let winB = 0;
  let tie = 0;
  for (const r of rows) {
    if (r.winner === "a") winA += 1;
    else if (r.winner === "b") winB += 1;
    else tie += 1;
  }

  const columns: ColumnsType<Row> = [
    {
      title: "Metric",
      dataIndex: "metric",
      key: "metric",
      render: (m: string) => formatMetric(m),
    },
    {
      title: `A · ${run_a_name}`,
      key: "a",
      width: 160,
      render: () => <Tag color="orange">baseline</Tag>,
    },
    {
      title: `B · ${run_b_name}`,
      key: "b",
      width: 160,
      render: () => <Tag color="green">new</Tag>,
    },
    {
      title: "Δ (B − A)",
      dataIndex: "delta",
      key: "delta",
      width: 160,
      sorter: (a, b) => a.delta - b.delta,
      render: (d: number) => {
        const color = d > 0 ? "#3f8600" : d < 0 ? "#cf1322" : "#999";
        const arrow = d > 0 ? "↑" : d < 0 ? "↓" : "→";
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
      width: 90,
      sorter: (a, b) => (a.pct ?? 0) - (b.pct ?? 0),
      render: (p: number | null) =>
        p === null || p === undefined ? "—" : `${p.toFixed(1)}%`,
    },
    {
      title: "Winner",
      dataIndex: "winner",
      key: "winner",
      width: 120,
      render: (w: Row["winner"]) => (
        <Tag color={WINNER_COLOR[w]}>{WINNER_LABEL[w]}</Tag>
      ),
    },
  ];

  return (
    <Card title="Run 对比 / Compare" size="small">
      <div
        style={{
          display: "flex",
          gap: 16,
          marginBottom: 16,
          flexWrap: "wrap",
        }}
      >
        <Statistic
          title="A 胜 metrics"
          value={winA}
          valueStyle={{ color: "#fa8c16", fontSize: 20 }}
        />
        <Statistic
          title="B 胜 metrics"
          value={winB}
          valueStyle={{ color: "#3f8600", fontSize: 20 }}
        />
        <Statistic
          title="平 / Tie"
          value={tie}
          valueStyle={{ color: "#999", fontSize: 20 }}
        />
      </div>
      <Table<Row>
        rowKey="metric"
        columns={columns}
        dataSource={rows}
        size="small"
        pagination={false}
        bordered
      />
    </Card>
  );
}
