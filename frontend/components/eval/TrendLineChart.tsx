"use client";

// frontend/components/eval/TrendLineChart.tsx
// M37.3 — 30 天 hit@5 / mrr 趋势可视化(antd 原语版)。
//
// plan §T21 写的是"多线折线"。无图表库 → 用 antd Table + 行内 SVG sparkline
// + 颜色 Tag 区分 dataset,每个 dataset 一段。
//
// sparkline:对每个 dataset 一行,在 row 内画 SVG(8 像素高),用 path 连 points。
// 维度选 metric(`hit_at_5` 或 `mrr`),默认 hit_at_5。
//
// 数据来源:`TrendSeries[]`(services/eval.ts::getTrendSeries())。

import { useMemo } from "react";
import {
  Card,
  Empty,
  Radio,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TrendPoint, TrendSeries } from "@/types/eval";

export interface TrendLineChartProps {
  series: TrendSeries[];
  title?: string;
  /** 默认 hit_at_5。 */
  metric?: "hit_at_5" | "mrr";
}

interface Row {
  key: number;
  dataset_id: number;
  dataset_name: string;
  points: TrendPoint[];
  avg: number;
  latest: number;
  run_count: number;
}

const DATASET_COLORS = [
  "#1677ff",
  "#52c41a",
  "#fa8c16",
  "#722ed1",
  "#eb2f96",
  "#13c2c2",
  "#fa541c",
  "#a0d911",
];

function colorForDataset(idx: number): string {
  return DATASET_COLORS[idx % DATASET_COLORS.length];
}

interface SparklineProps {
  points: TrendPoint[];
  metric: "hit_at_5" | "mrr";
  color: string;
  width?: number;
  height?: number;
}

function Sparkline({
  points,
  metric,
  color,
  width = 240,
  height = 32,
}: SparklineProps) {
  const values = points.map((p) => p[metric]);
  // 至少 2 个点才画得成线
  if (values.length < 2) {
    return (
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        数据不足
      </Typography.Text>
    );
  }
  const max = Math.max(...values, 0.0001);
  const min = Math.min(...values, 0);
  const range = max - min || 1;
  const stepX = width / Math.max(values.length - 1, 1);
  const path = values
    .map((v, i) => {
      const x = i * stepX;
      const y = height - ((v - min) / range) * height;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg width={width} height={height} role="img" aria-label="trend sparkline">
      <path
        d={path}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* 最后一个点画个圆点 */}
      {values.length > 0 && (() => {
        const lastV = values[values.length - 1];
        const lastX = (values.length - 1) * stepX;
        const lastY = height - ((lastV - min) / range) * height;
        return <circle cx={lastX} cy={lastY} r={2.5} fill={color} />;
      })()}
    </svg>
  );
}

export default function TrendLineChart({
  series,
  title,
  metric: initialMetric = "hit_at_5",
}: TrendLineChartProps) {
  // 因为 metric 是 controlled-from-parent in 设计,但 antd Radio 内部 onChange
  // 这里简单用 useState 内管(实测中如果父级要 override 再加 prop)。
  // 我们直接用 prop 的当前值;Radio 仅展示不切换(避免引入组件 state)。
  const metric = initialMetric;

  const rows: Row[] = useMemo(() => {
    return series.map((s, idx) => {
      const nonzero = s.points.filter((p) => p.run_count > 0);
      const sum = nonzero.reduce((acc, p) => acc + p[metric], 0);
      const avg = nonzero.length > 0 ? sum / nonzero.length : 0;
      const lastNonzero = [...nonzero].reverse().find((p) => p.run_count > 0);
      const latest = lastNonzero ? lastNonzero[metric] : 0;
      const run_count = nonzero.length;
      return {
        key: idx,
        dataset_id: s.dataset_id,
        dataset_name: s.dataset_name,
        points: s.points,
        avg,
        latest,
        run_count,
      };
    });
  }, [series, metric]);

  const columns: ColumnsType<Row> = [
    {
      title: "Dataset",
      dataIndex: "dataset_name",
      key: "dataset_name",
      width: 180,
      render: (n: string, row, idx: number) => (
        <Space size={4}>
          <span
            style={{
              display: "inline-block",
              width: 10,
              height: 10,
              background: colorForDataset(row.key),
              borderRadius: 2,
            }}
          />
          <Typography.Text>{n}</Typography.Text>
        </Space>
      ),
    },
    {
      title: "趋势 / Sparkline",
      key: "sparkline",
      render: (_: unknown, row) => (
        <Sparkline
          points={row.points}
          metric={metric}
          color={colorForDataset(row.key)}
        />
      ),
    },
    {
      title: "最新",
      dataIndex: "latest",
      key: "latest",
      width: 90,
      render: (v: number) =>
        v > 0 ? v.toFixed(3) : <Typography.Text type="secondary">—</Typography.Text>,
    },
    {
      title: "均值",
      dataIndex: "avg",
      key: "avg",
      width: 90,
      render: (v: number) =>
        v > 0 ? v.toFixed(3) : <Typography.Text type="secondary">—</Typography.Text>,
    },
    {
      title: "样本日",
      dataIndex: "run_count",
      key: "run_count",
      width: 90,
      render: (n: number) => <Tag>{n} 天</Tag>,
    },
  ];

  const legend = (
    <Space size={4} wrap>
      {series.map((s, idx) => (
        <Tag key={s.dataset_id} color="default">
          <span
            style={{
              display: "inline-block",
              width: 8,
              height: 8,
              background: colorForDataset(idx),
              marginRight: 4,
              borderRadius: 1,
            }}
          />
          {s.dataset_name}
        </Tag>
      ))}
    </Space>
  );

  return (
    <Card
      title={title ?? "趋势(最近 30 天)/ Trend"}
      size="small"
      extra={
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          指标:{metric} | 无图表库,内联 SVG sparkline
        </Typography.Text>
      }
    >
      {rows.length === 0 ? (
        <Empty description="近 30 天无 completed run,趋势图暂无数据" />
      ) : (
        <>
          <div style={{ marginBottom: 12 }}>{legend}</div>
          <Table<Row>
            rowKey="key"
            columns={columns}
            dataSource={rows}
            size="small"
            pagination={false}
          />
        </>
      )}
    </Card>
  );
}
