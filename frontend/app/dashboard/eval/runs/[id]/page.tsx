"use client";

// frontend/app/dashboard/eval/runs/[id]/page.tsx
// M37.3 — 单个 run 的详情页(/dashboard/eval/runs/{id})。
//
// 布局:
//   1. 顶部:EvalRun info card + 「对比基线」按钮(支持 ?compare_to=A_id query)
//   2. MetricsRadar(5 维检索指标)—— 含基线对比 delta(若 ?compare_to 有)
//   3. 折叠面板:整体指标 / by_category / by_difficulty
//   4. FailureList(失败 case 表格 + judge reasoning 折叠)
//   5. 报告区:report_markdown 渲染(Markdown)
//
// 数据来源:GET /api/v1/eval/runs/{id}?include_results=true
// 轮询:5s 一次(跑中状态时;终态不再轮询)
// ?compare_to=<run_id>:进入时拿 baseline(从 URL parse),metrics 对比算 delta。

import { useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Card,
  Collapse,
  Descriptions,
  Empty,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
} from "antd";
import {
  ArrowLeftOutlined,
  ReloadOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { cancelRun, compareRuns, getRun } from "@/services/eval_run";
import type {
  EvalRunCancel,
  EvalRunCompareResponse,
  EvalRunDetail,
  EvalRunDetailWithResults,
  EvalRunMetrics,
} from "@/types/eval_run";
import CategoryBreakdownChart from "@/components/eval/CategoryBreakdownChart";
import CompareDelta from "@/components/eval/CompareDelta";
import FailureList from "@/components/eval/FailureList";
import MetricsRadar from "@/components/eval/MetricsRadar";
import RunProgressBar from "@/components/eval/RunProgressBar";

const STATUS_COLOR: Record<string, string> = {
  pending: "default",
  running: "processing",
  completed: "success",
  failed: "error",
  cancelled: "warning",
};

const STATUS_LABEL: Record<string, string> = {
  pending: "等待中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export default function EvalRunDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { message } = App.useApp();

  const runId = Number(params?.id);
  const compareToIdRaw = searchParams?.get("compare_to");
  const compareToId = compareToIdRaw ? Number(compareToIdRaw) : null;

  // 详情(include_results=true 让前端能渲 failure list)
  const {
    data: run,
    isLoading,
    refetch,
  } = useQuery<EvalRunDetailWithResults>({
    queryKey: ["eval-run-detail", runId],
    queryFn: () => getRun(runId, { includeResults: true, resultsPageSize: 100 }),
    enabled: Number.isFinite(runId),
    refetchInterval: (q) => {
      const data = q.state.data as EvalRunDetailWithResults | undefined;
      if (!data) return false;
      if (data.status === "running" || data.status === "pending") return 5_000;
      return false;
    },
  });

  // 基线 run(若 ?compare_to)
  const baselineRunId = compareToId !== null && compareToId !== runId ? compareToId : null;
  const { data: baseline } = useQuery<EvalRunDetail | null>({
    queryKey: ["eval-run-detail", baselineRunId],
    queryFn: async () => {
      if (!baselineRunId) return null;
      const res = await getRun(baselineRunId);
      return res;
    },
    enabled: Boolean(baselineRunId),
  });

  // 完整 compare 响应(只在「详情页对比」按钮按了之后才拿)
  const [compare, setCompare] = useState<EvalRunCompareResponse | null>(null);
  const compareRunsQuery = useQuery({
    queryKey: ["eval-compare-runs", runId, baselineRunId],
    queryFn: async () => {
      if (!baselineRunId || !runId || baselineRunId === runId) return null;
      return compareRuns({ run_id_a: baselineRunId, run_id_b: runId });
    },
    enabled: Boolean(baselineRunId) && Boolean(runId) && baselineRunId !== runId,
  });
  useEffect(() => {
    if (compareRunsQuery.data) setCompare(compareRunsQuery.data);
  }, [compareRunsQuery.data]);

  // 派生:基线 retrieval 用于 MetricsRadar 的 delta
  const baselineRetrieval = useMemo(() => {
    if (!baseline?.metrics_json) return null;
    return baseline.metrics_json.retrieval;
  }, [baseline]);

  if (!Number.isFinite(runId)) {
    return (
      <div style={{ padding: 24 }}>
        <Empty description="无效的 run id" />
      </div>
    );
  }

  if (isLoading || !run) {
    return (
      <div style={{ padding: 24, textAlign: "center" }}>
        <Spin tip="加载中..." />
      </div>
    );
  }

  const metrics = run.metrics_json;
  const isTerminal =
    run.status === "completed" ||
    run.status === "failed" ||
    run.status === "cancelled";

  return (
    <div style={{ padding: 24 }}>
      {/* 顶部导航 + 操作 */}
      <div
        style={{
          marginBottom: 16,
          display: "flex",
          alignItems: "center",
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() => router.push("/dashboard/eval")}
        >
          返回看板
        </Button>
        <h2 style={{ margin: 0, marginRight: "auto" }}>
          Run #{run.id} 详情
        </h2>
        <Button icon={<ReloadOutlined />} onClick={() => refetch()}>
          刷新
        </Button>
        {!isTerminal && (
          <Button
            danger
            onClick={async () => {
              try {
                await cancelRun(run.id, {
                  reason: "用户从详情页取消",
                } satisfies EvalRunCancel);
                message.success("已取消");
                refetch();
              } catch (e) {
                message.error(
                  `取消失败:${e instanceof Error ? e.message : "未知错误"}`,
                );
              }
            }}
          >
            取消 Run
          </Button>
        )}
        {baselineRunId ? (
          <Button
            onClick={() => {
              // 清掉 compare_to query
              router.push(`/dashboard/eval/runs/${runId}`);
              setCompare(null);
            }}
          >
            清除对比基线
          </Button>
        ) : (
          <Button
            icon={<SwapOutlined />}
            onClick={() => {
              // 给一个 prompt 让用户输入 baseline run id(轻量,不做 modal 选 run 列表)
              const v = window.prompt(
                "输入基线 run id(对比 baseline → 当前 run):",
                "",
              );
              if (!v) return;
              const n = Number(v);
              if (!Number.isFinite(n) || n === runId) {
                message.warning("基线 run id 无效或等于当前 run");
                return;
              }
              router.push(`/dashboard/eval/runs/${runId}?compare_to=${n}`);
            }}
          >
            对比基线
          </Button>
        )}
      </div>

      {/* Info card */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions
          size="small"
          column={{ xs: 1, sm: 2, md: 3 }}
          items={[
            {
              key: "status",
              label: "状态",
              children: (
                <Space>
                  <Tag color={STATUS_COLOR[run.status] ?? "default"}>
                    {STATUS_LABEL[run.status] ?? run.status}
                  </Tag>
                  <RunProgressBar
                    status={run.status}
                    completed={run.completed_items}
                    total={run.total_items}
                    errorMessage={run.error_message}
                  />
                </Space>
              ),
            },
            { key: "ds", label: "Dataset", children: <Tag>#{run.dataset_id}</Tag> },
            {
              key: "started",
              label: "开始时间",
              children: run.started_at
                ? new Date(run.started_at).toLocaleString("zh-CN")
                : "—",
            },
            {
              key: "finished",
              label: "完成时间",
              children: run.finished_at
                ? new Date(run.finished_at).toLocaleString("zh-CN")
                : "—",
            },
            {
              key: "trace",
              label: "Trace ID",
              children: run.trace_id ? (
                <Typography.Text code copyable>
                  {run.trace_id}
                </Typography.Text>
              ) : (
                "—"
              ),
            },
            {
              key: "config",
              label: "Config",
              children: (
                <Typography.Text
                  code
                  style={{ fontSize: 11 }}
                  copyable={{ text: JSON.stringify(run.config, null, 2) }}
                >
                  {JSON.stringify(run.config).slice(0, 60)}
                  {JSON.stringify(run.config).length > 60 ? "..." : ""}
                </Typography.Text>
              ),
            },
          ]}
        />
      </Card>

      {/* MetricsRadar(5 维) */}
      {metrics ? (
        <div style={{ marginBottom: 16 }}>
          <MetricsRadar
            retrieval={metrics.retrieval}
            baseline={baselineRetrieval}
            title={
              baselineRetrieval
                ? `检索指标 / vs Run #${baselineRunId}`
                : "检索指标 / Retrieval Metrics"
            }
          />
        </div>
      ) : (
        <Card style={{ marginBottom: 16 }}>
          <Empty description="评测未完成,无 metrics 数据" />
        </Card>
      )}

      {/* 指标折叠面板 */}
      {metrics && (
        <Collapse
          style={{ marginBottom: 16 }}
          defaultActiveKey={["overall"]}
          items={[
            {
              key: "overall",
              label: "整体指标 / Overall",
              children: (
                <OverallMetricsPanel metrics={metrics} />
              ),
            },
            {
              key: "by_category",
              label: "按 Category / By Category",
              children: (
                <CategoryBreakdownChart
                  title="by_category · Hit@5"
                  group_label="Category"
                  by_category={metrics.by_category}
                  group_by="category"
                />
              ),
            },
            {
              key: "by_difficulty",
              label: "按 Difficulty / By Difficulty",
              children: (
                <CategoryBreakdownChart
                  title="by_difficulty · Hit@5"
                  group_label="Difficulty"
                  by_difficulty={metrics.by_difficulty}
                  group_by="difficulty"
                />
              ),
            },
          ]}
        />
      )}

      {/* FailureList */}
      {run.results && run.results.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <FailureList results={run.results} />
        </div>
      )}

      {/* Compare:若 ?compare_to 有,展示 CompareDelta */}
      {compare && baseline && (
        <div style={{ marginBottom: 16 }}>
          <Card
            title={`对比 Run #${baseline.id} → Run #${run.id}`}
            size="small"
          >
            <CompareDelta compare={compare} />
          </Card>
        </div>
      )}

      {/* Markdown 报告 */}
      {run.report_markdown && (
        <Card title="报告 / Report" size="small">
          <pre
            style={{
              background: "#fafafa",
              padding: 12,
              fontSize: 12,
              maxHeight: 400,
              overflow: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {run.report_markdown}
          </pre>
        </Card>
      )}
    </div>
  );
}

// ===========================================================================
// 子组件:整体指标 panel(4 列 statistic grid)
// ===========================================================================

interface OverallMetricsPanelProps {
  metrics: EvalRunMetrics;
}

function OverallMetricsPanel({ metrics }: OverallMetricsPanelProps) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
        gap: 16,
      }}
    >
      <Statistic
        title="Hit@5"
        value={metrics.retrieval.hit_at_5.toFixed(3)}
      />
      <Statistic
        title="Hit@10"
        value={metrics.retrieval.hit_at_10.toFixed(3)}
      />
      <Statistic title="MRR" value={metrics.retrieval.mrr.toFixed(3)} />
      <Statistic
        title="NDCG@10"
        value={metrics.retrieval.ndcg_at_10.toFixed(3)}
      />
      <Statistic
        title="Recall@10"
        value={metrics.retrieval.recall_at_10.toFixed(3)}
      />
      <Statistic
        title="Faithfulness avg"
        value={metrics.answer.faithfulness_avg.toFixed(3)}
      />
      <Statistic
        title="Answer Relevancy avg"
        value={metrics.answer.answer_relevancy_avg.toFixed(3)}
      />
      <Statistic
        title="Keyword Hit Rate"
        value={(metrics.answer.keyword_hit_rate * 100).toFixed(1) + "%"}
      />
      <Statistic
        title="Judge 调用总数"
        value={metrics.answer.llm_judge_total_calls}
      />
      <Statistic
        title="完成 / 失败"
        value={`${metrics.totals.items_success} / ${metrics.totals.items_failed}`}
      />
    </div>
  );
}
