"use client";

// frontend/components/eval/FailureList.tsx
// M37.3 — Run 失败 case 列表(可展开 judge reasoning)。
//
// 输入 `results`:来自 GET /api/v1/eval/runs/{id}?include_results=true 的
// results 数组。我们筛「失败」——定义是 ``error_message != null`` OR
// ``answer_metrics == null``(judge 没跑成功)OR
// ``retrieval_metrics.hit_at_5 == 0``(检索全 miss)。
//
// 渲染:Table 折叠行(default expand by 错误,有 judge reasoning 的展开)。
// 折叠内容:query / retrieved docs / answer / 失败原因 + judge reasoning。

import { useMemo } from "react";
import {
  Card,
  Empty,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType, ExpandableConfig } from "antd/es/table/interface";
import type { EvalRunResultItem } from "@/types/eval_run";

export interface FailureListProps {
  /** 完整 results 列表(组件内筛失败)。 */
  results: EvalRunResultItem[];
  /** 标题。默认 "失败 Cases / Failures"。 */
  title?: string;
  /** 最大显示数,默认 20(超出折叠"还有 N 条")。 */
  max_show?: number;
}

interface FailureRow {
  key: number;
  result: EvalRunResultItem;
  reason: string;
}

function classifyFailure(r: EvalRunResultItem): string | null {
  if (r.error_message) return `运行时错误:${r.error_message}`;
  // 优先级:检索全 miss 比 judge 未跑更具体——优先报检索问题
  if (r.retrieval_metrics.hit_at_5 === 0)
    return "检索全 miss(Hit@5=0)";
  if (!r.answer_metrics) return "judge 未跑成功";
  const faith = r.answer_metrics.faithfulness_avg;
  if (faith !== null && faith !== undefined && faith < 1)
    return `Faithfulness 偏低 (${faith}/2)`;
  const ar = r.answer_metrics.answer_relevancy_avg;
  if (ar !== null && ar !== undefined && ar < 1)
    return `Answer Relevancy 偏低 (${ar}/2)`;
  return null;
}

export default function FailureList({
  results,
  title,
  max_show = 20,
}: FailureListProps) {
  const rows: FailureRow[] = useMemo(() => {
    return results
      .map((r) => ({ result: r, reason: classifyFailure(r) }))
      .filter((row): row is FailureRow => row.reason !== null)
      .map((row, i) => ({ ...row, key: i }));
  }, [results]);

  const visible = rows.slice(0, max_show);
  const hidden = rows.length - visible.length;

  const columns: ColumnsType<FailureRow> = [
    {
      title: "#",
      dataIndex: "result",
      key: "idx",
      width: 50,
      render: (_: unknown, row, idx: number) => (
        <Typography.Text type="secondary">{idx + 1}</Typography.Text>
      ),
    },
    {
      title: "Query",
      dataIndex: ["result", "query"],
      key: "query",
      ellipsis: true,
      render: (q: string) => (
        <Typography.Text style={{ maxWidth: 380 }} ellipsis={{ tooltip: q }}>
          {q}
        </Typography.Text>
      ),
    },
    {
      title: "Hit@5",
      key: "hit5",
      width: 80,
      render: (_: unknown, row) =>
        row.result.retrieval_metrics.hit_at_5.toFixed(2),
    },
    {
      title: "Faith",
      key: "faith",
      width: 70,
      render: (_: unknown, row) => {
        const f = row.result.answer_metrics?.faithfulness_avg;
        return f === null || f === undefined ? "—" : `${f}/2`;
      },
    },
    {
      title: "失败原因",
      dataIndex: "reason",
      key: "reason",
      render: (reason: string) => <Tag color="red">{reason}</Tag>,
    },
  ];

  const expandable: ExpandableConfig<FailureRow> = {
    rowExpandable: (row) =>
      Boolean(row.result.error_message) ||
      Boolean(row.result.answer),
    expandedRowRender: (row) => {
      const r = row.result;
      return (
        <div style={{ padding: 8, background: "#fafafa" }}>
          <Space direction="vertical" size="small" style={{ width: "100%" }}>
            <div>
              <Typography.Text strong>Query:</Typography.Text> {r.query}
            </div>
            <div>
              <Typography.Text strong>Retrieved doc IDs:</Typography.Text>{" "}
              {r.retrieved_doc_ids.length > 0
                ? r.retrieved_doc_ids.join(", ")
                : "(空)"}
            </div>
            {r.retrieved_contexts && r.retrieved_contexts.length > 0 && (
              <div>
                <Typography.Text strong>Top context:</Typography.Text>{" "}
                <Typography.Text type="secondary">
                  {r.retrieved_contexts[0].slice(0, 300)}
                  {r.retrieved_contexts[0].length > 300 ? "..." : ""}
                </Typography.Text>
              </div>
            )}
            {r.answer && (
              <div>
                <Typography.Text strong>LLM Answer:</Typography.Text>{" "}
                <Typography.Paragraph
                  copyable={{ tooltips: ["复制", "已复制"] }}
                  style={{ marginBottom: 0, display: "inline" }}
                >
                  {r.answer}
                </Typography.Paragraph>
              </div>
            )}
            {r.error_message && (
              <div>
                <Typography.Text strong type="danger">
                  Error:
                </Typography.Text>{" "}
                <Typography.Text type="danger">{r.error_message}</Typography.Text>
              </div>
            )}
            {r.llm_judge_calls && r.llm_judge_calls.length > 0 && (
              <details>
                <summary style={{ cursor: "pointer", color: "#666" }}>
                  Judge reasoning ({r.llm_judge_calls.length} calls)
                </summary>
                <pre
                  style={{
                    fontSize: 12,
                    background: "#fff",
                    padding: 8,
                    marginTop: 8,
                    border: "1px solid #ddd",
                    borderRadius: 4,
                    maxHeight: 300,
                    overflow: "auto",
                  }}
                >
                  {JSON.stringify(r.llm_judge_calls, null, 2)}
                </pre>
              </details>
            )}
          </Space>
        </div>
      );
    },
  };

  return (
    <Card
      title={title ?? "失败 Cases / Failures"}
      size="small"
      extra={
        rows.length > 0 ? (
          <Tag color="red">{rows.length} 失败</Tag>
        ) : null
      }
    >
      {rows.length === 0 ? (
        <Empty description="无失败 case 🎉" />
      ) : (
        <>
          <Table<FailureRow>
            rowKey="key"
            columns={columns}
            dataSource={visible}
            size="small"
            pagination={false}
            expandable={expandable}
            bordered
          />
          {hidden > 0 && (
            <div
              style={{
                textAlign: "center",
                color: "#999",
                padding: 8,
                fontSize: 12,
              }}
            >
              ...还有 {hidden} 条失败,详情页「报告」段查看
            </div>
          )}
        </>
      )}
    </Card>
  );
}
