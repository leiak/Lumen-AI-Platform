"use client";

// frontend/components/eval/CategoryBreakdownChart.tsx
// M37.3 — 按 category / difficulty 拆分的指标表(antd 原语版)。
//
// plan §T21 写的是"柱状图按 category 分组 hit@5"。无图表库 → 用 antd Table
// + 内联 Progress 条展示每个类别的 hit@5 / mrr / count。视觉上比真柱状图
// 弱,但能完整表达跨类对比 + 排序,信息密度更高。
//
// 入参 `group_by`:决定表格按 `by_category` 还是 `by_difficulty` 聚合。

import { Card, Empty, Progress, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";

export interface CategoryBreakdown {
  hit_at_5: number;
  mrr: number;
  count: number;
}

export interface CategoryBreakdownChartProps {
  /** 标题。 */
  title: string;
  /** 拆分维度 key 的中文标签(列名)。 */
  group_label: string;
  /** spec §4.2 metrics_json.by_category。 */
  by_category?: Record<string, CategoryBreakdown> | null;
  /** spec §4.2 metrics_json.by_difficulty。 */
  by_difficulty?: Record<string, CategoryBreakdown> | null;
  /** 选择哪个 group:`"category"` / `"difficulty"`。默认 category。 */
  group_by?: "category" | "difficulty";
}

interface Row {
  key: string;
  group: string;
  hit_at_5: number;
  mrr: number;
  count: number;
}

const CATEGORY_COLORS: Record<string, string> = {
  factual: "blue",
  reasoning: "purple",
  multi_hop: "cyan",
  keyword_heavy: "orange",
  out_of_scope: "default",
};

const DIFFICULTY_COLORS: Record<string, string> = {
  easy: "green",
  medium: "gold",
  hard: "volcano",
};

function colorForGroup(group: string, by: "category" | "difficulty"): string {
  if (by === "category") return CATEGORY_COLORS[group] ?? "default";
  return DIFFICULTY_COLORS[group] ?? "default";
}

export default function CategoryBreakdownChart({
  title,
  group_label,
  by_category,
  by_difficulty,
  group_by = "category",
}: CategoryBreakdownChartProps) {
  const source =
    group_by === "category" ? by_category : by_difficulty;

  if (!source) {
    return (
      <Card title={title} size="small">
        <Empty description="无分类数据(评测未跑完或未提供分类)" />
      </Card>
    );
  }

  const rows: Row[] = Object.entries(source)
    .map(([k, v]) => ({
      key: k,
      group: k,
      hit_at_5: v.hit_at_5,
      mrr: v.mrr,
      count: v.count,
    }))
    .sort((a, b) => b.hit_at_5 - a.hit_at_5);

  const columns: ColumnsType<Row> = [
    {
      title: group_label,
      dataIndex: "group",
      key: "group",
      width: 140,
      render: (g: string) => (
        <Tag color={colorForGroup(g, group_by)}>{g}</Tag>
      ),
    },
    {
      title: "样本数 / Count",
      dataIndex: "count",
      key: "count",
      width: 100,
      render: (n: number) => n.toString(),
    },
    {
      title: "Hit@5",
      dataIndex: "hit_at_5",
      key: "hit_at_5",
      render: (v: number) => (
        <div style={{ minWidth: 180 }}>
          <Progress
            percent={Math.round(v * 100)}
            size="small"
            format={(p) => `${v.toFixed(3)} (${p}%)`}
          />
        </div>
      ),
    },
    {
      title: "MRR",
      dataIndex: "mrr",
      key: "mrr",
      width: 120,
      render: (v: number) => (
        <Progress
          percent={Math.round(v * 100)}
          size="small"
          strokeColor="#1677ff"
          format={() => v.toFixed(3)}
        />
      ),
    },
  ];

  return (
    <Card title={title} size="small">
      <Table<Row>
        rowKey="key"
        columns={columns}
        dataSource={rows}
        size="small"
        pagination={false}
        bordered
      />
    </Card>
  );
}
