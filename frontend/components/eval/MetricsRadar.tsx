"use client";

// frontend/components/eval/MetricsRadar.tsx
// M37.3 — 5 维评测指标可视化(antd 原语版)。
//
// 设计选择:**plan §T21 写的是 recharts <Radar>,但项目没装图表库(用户
// 决策 2026-08-06:用 antd 原语,零新依赖)**。所以这里用 Card + Progress
// + Statistic 拼一个「类雷达布局」——5 个维度每个一行,数字 + 进度条 + 基线
// 对比 delta。视觉上不如真雷达图直观,但能完整表达相对差距,跟项目其它
// 页面(无图表)风格一致。
//
// 显示维度顺序:Hit@5 / Hit@10 / MRR / NDCG@10 / Recall@10
// —— 跟 spec §4.2 metrics_json.retrieval 子对象字段顺序一致。

import { Card, Col, Progress, Row, Statistic, Tooltip } from "antd";
import { ArrowUpOutlined, ArrowDownOutlined, MinusOutlined } from "@ant-design/icons";

export interface MetricsRadarProps {
  /** 当前 run 的 retrieval 子对象(5 维)。 */
  retrieval: {
    hit_at_5: number;
    hit_at_10: number;
    mrr: number;
    ndcg_at_10: number;
    recall_at_10: number;
  };
  /** 可选:基线 run 的 retrieval(用于 delta 计算)。null = 不显示 delta。 */
  baseline?: {
    hit_at_5: number;
    hit_at_10: number;
    mrr: number;
    ndcg_at_10: number;
    recall_at_10: number;
  } | null;
  /** 自定义标题,默认"检索指标 / Retrieval"。 */
  title?: string;
}

interface Dim {
  key: keyof MetricsRadarProps["retrieval"];
  label: string;
  desc: string;
}

const DIMS: Dim[] = [
  { key: "hit_at_5", label: "Hit@5", desc: "前 5 个结果是否命中至少一个 expected doc" },
  { key: "hit_at_10", label: "Hit@10", desc: "前 10 个结果是否命中至少一个" },
  { key: "mrr", label: "MRR", desc: "第一个命中的倒数排名(0-1)" },
  { key: "ndcg_at_10", label: "NDCG@10", desc: "二元相关性 NDCG,top-10" },
  { key: "recall_at_10", label: "Recall@10", desc: "前 10 个命中占 expected 总数比例" },
];

function fmtPct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function deltaTone(delta: number): {
  arrow: JSX.Element;
  color: string;
  label: string;
} {
  if (delta > 0.0005) {
    return { arrow: <ArrowUpOutlined />, color: "#3f8600", label: "↑" };
  }
  if (delta < -0.0005) {
    return { arrow: <ArrowDownOutlined />, color: "#cf1322", label: "↓" };
  }
  return { arrow: <MinusOutlined />, color: "#999", label: "→" };
}

export default function MetricsRadar({
  retrieval,
  baseline,
  title,
}: MetricsRadarProps) {
  const baseTitle = title ?? "检索指标 / Retrieval Metrics";

  return (
    <Card title={baseTitle} size="small">
      <Row gutter={[16, 16]}>
        {DIMS.map((d) => {
          const value = retrieval[d.key];
          const baseValue = baseline?.[d.key] ?? null;
          const delta = baseValue !== null ? value - baseValue : null;
          const tone = delta !== null ? deltaTone(delta) : null;
          // 进度条按百分比显示(0-1 → 0-100)
          const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
          return (
            <Col xs={24} sm={12} md={8} lg={8} xl={8} key={d.key}>
              <Card size="small" bordered>
                <Statistic
                  title={
                    <Tooltip title={d.desc}>
                      <span>{d.label}</span>
                    </Tooltip>
                  }
                  value={fmtPct(value)}
                  valueStyle={{ fontSize: 22 }}
                />
                <Progress
                  percent={pct}
                  showInfo={false}
                  size="small"
                  strokeColor={
                    pct >= 80
                      ? "#3f8600"
                      : pct >= 50
                        ? "#faad14"
                        : "#cf1322"
                  }
                />
                {tone && delta !== null && (
                  <div
                    style={{
                      fontSize: 12,
                      color: tone.color,
                      marginTop: 4,
                    }}
                  >
                    {tone.arrow}{" "}
                    <span>
                      Δ {delta >= 0 ? "+" : ""}
                      {(delta * 100).toFixed(2)}%{" "}
                      <span style={{ color: "#999" }}>
                        vs {(baseValue ?? 0).toFixed(3)}
                      </span>
                    </span>
                  </div>
                )}
              </Card>
            </Col>
          );
        })}
      </Row>
    </Card>
  );
}
