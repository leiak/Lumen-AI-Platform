"use client";

// frontend/app/dashboard/eval/page.tsx
// M37.3 — /dashboard/eval 主页(RAG 评测 dashboard)。
//
// 布局(从顶到底):
//   1. KPI 卡片行:本周评测次数 / 本周平均 Hit@5 / 历史平均 / 上次对比 delta
//   2. TrendLineChart(最近 30 天 hit@5 / mrr,按 dataset 拆线)
//   3. Run 列表(table + 「详情」+ 「对比」+ 「新建评测」modal)
//
// 数据来源:`services/eval.ts::getDashboardSummary()` —— 后端无 aggregate
// endpoint,前端客户端聚合(listRuns → completed run 并行 getRun → 聚合)。
// 详情见 services/eval.ts 顶部注释。

import { useMemo, useState } from "react";

import {
  App,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
} from "antd";
import {
  PlayCircleOutlined,
  ReloadOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { listDatasets, getDataset } from "@/services/eval_dataset";
import { startRun, cancelRun } from "@/services/eval_run";
import { getDashboardSummary } from "@/services/eval";
import { knowledgeApi } from "@/services/knowledge";
import type { EvalDatasetListItem, EvalDatasetDetail, EvalDatasetListResult } from "@/types/eval_dataset";
import type {
  EvalRunCancel,
  EvalRunConfig,
  EvalRunCreate,
  EvalRunListItem,
  EvalRunStatus,
} from "@/types/eval_run";
import type { DashboardKPI, EvalDashboardSummary } from "@/types/eval";
import RunConfigForm from "@/components/eval/RunConfigForm";
import RunProgressBar from "@/components/eval/RunProgressBar";
import TrendLineChart from "@/components/eval/TrendLineChart";

const STATUS_LABEL: Record<EvalRunStatus, string> = {
  pending: "等待中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const STATUS_COLOR: Record<EvalRunStatus, string> = {
  pending: "default",
  running: "processing",
  completed: "success",
  failed: "error",
  cancelled: "warning",
};

const KPI_TONE_COLOR: Record<
  NonNullable<DashboardKPI["deltaTone"]>,
  string
> = {
  up: "#3f8600",
  down: "#cf1322",
  neutral: "#999",
};

export default function EvalDashboardPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const { message } = App.useApp();

  const [startOpen, setStartOpen] = useState(false);
  // 对比:被勾选的两个 run id(进入 compare page 用)
  const [compareSelection, setCompareSelection] = useState<number[]>([]);

  // --- dashboard 数据 ---
  const {
    data: summary,
    isLoading: summaryLoading,
    refetch: refetchSummary,
  } = useQuery<EvalDashboardSummary>({
    queryKey: ["eval-dashboard-summary"],
    queryFn: () => getDashboardSummary({ lookback_days: 30 }),
    refetchInterval: 30_000, // 30s 自动刷新(主页 KPI 不需要 5s 那么密)
  });

  // --- dataset 列表(「新建评测」modal 用)---
  const { data: dsData } = useQuery<EvalDatasetListResult>({
    queryKey: ["eval-datasets"],
    queryFn: () => listDatasets({ page: 1, page_size: 100 }),
  });

  const startMut = useMutation({
    mutationFn: (payload: EvalRunCreate) => startRun(payload),
    onSuccess: (run) => {
      message.success(`已启动 Run #${run.id}`);
      setStartOpen(false);
      qc.invalidateQueries({ queryKey: ["eval-dashboard-summary"] });
      qc.invalidateQueries({ queryKey: ["eval-runs"] });
    },
    onError: (e: Error) => message.error(`启动失败:${e.message}`),
  });

  const cancelMut = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload?: EvalRunCancel }) =>
      cancelRun(id, payload),
    onSuccess: (run) => {
      message.success(`已取消 Run #${run.id}`);
      qc.invalidateQueries({ queryKey: ["eval-dashboard-summary"] });
    },
    onError: (e: Error) => message.error(`取消失败:${e.message}`),
  });

  // --- 派生:KPI cards ---
  const kpiCards = useMemo(() => {
    if (!summary) return [] as DashboardKPI[];
    return summary.kpis;
  }, [summary]);

  // --- 派生:run 列表 column ---
  const runColumns: ColumnsType<EvalRunListItem> = [
    {
      title: "Run #",
      dataIndex: "id",
      key: "id",
      width: 90,
      render: (id: number) => (
        <Button
          type="link"
          size="small"
          onClick={() => router.push(`/dashboard/eval/runs/${id}`)}
        >
          #{id}
        </Button>
      ),
    },
    {
      title: "Dataset",
      dataIndex: "dataset_id",
      key: "dataset_id",
      width: 90,
      render: (id: number) => <Tag color="blue">#{id}</Tag>,
    },
    {
      title: "进度 / 状态",
      key: "status",
      width: 220,
      render: (_, row) => (
        <RunProgressBar
          status={row.status}
          completed={row.completed_items}
          total={row.total_items}
          errorMessage={row.error_message}
        />
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status_text",
      width: 90,
      render: (s: EvalRunStatus) => (
        <Tag color={STATUS_COLOR[s]}>{STATUS_LABEL[s]}</Tag>
      ),
    },
    {
      title: "完成时间",
      dataIndex: "finished_at",
      key: "finished_at",
      width: 170,
      render: (s: string | null) =>
        s ? (
          new Date(s).toLocaleString("zh-CN")
        ) : (
          <Tag>未完成</Tag>
        ),
    },
    {
      title: "对比",
      key: "compare",
      width: 70,
      render: (_, row) => {
        const checked = compareSelection.includes(row.id);
        return (
          <input
            type="checkbox"
            checked={checked}
            disabled={row.status !== "completed"}
            onChange={(e) => {
              if (e.target.checked) {
                if (compareSelection.length >= 2) {
                  message.warning("最多选 2 个 run 对比");
                  return;
                }
                setCompareSelection([...compareSelection, row.id]);
              } else {
                setCompareSelection(
                  compareSelection.filter((id) => id !== row.id),
                );
              }
            }}
            aria-label={`Select run ${row.id} for compare`}
          />
        );
      },
    },
    {
      title: "操作",
      key: "actions",
      width: 130,
      fixed: "right",
      render: (_, row) => (
        <Space size="small" wrap>
          {(row.status === "pending" || row.status === "running") && (
            <Popconfirm
              title={`确定取消 Run #${row.id}?`}
              okText="取消 Run"
              okButtonProps={{ danger: true }}
              cancelText="不取消"
              onConfirm={() =>
                cancelMut.mutate({ id: row.id, payload: { reason: "用户取消" } })
              }
            >
              <Button type="link" size="small" danger>
                取消
              </Button>
            </Popconfirm>
          )}
          {row.status === "completed" && (
            <Button
              type="link"
              size="small"
              icon={<SwapOutlined />}
              onClick={() => router.push(`/dashboard/eval/runs/${row.id}`)}
            >
              详情
            </Button>
          )}
        </Space>
      ),
    },
  ];

  // --- 派生:KPI:第 3 张(历史平均)delta tone 上次对比 ---
  const latestCompare = summary?.latest_compare ?? null;

  return (
    <div style={{ padding: 24 }}>
      {/* 顶部:页头 + 操作按钮 */}
      <div
        style={{
          marginBottom: 16,
          display: "flex",
          alignItems: "center",
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <h2 style={{ margin: 0, marginRight: "auto" }}>RAG 评测看板</h2>
        <Button
          icon={<ReloadOutlined />}
          onClick={() => refetchSummary()}
          loading={summaryLoading}
        >
          刷新
        </Button>
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          onClick={() => setStartOpen(true)}
          disabled={!dsData?.items?.length}
        >
          新建评测
        </Button>
        {compareSelection.length === 2 && (
          <Button
            type="primary"
            ghost
            icon={<SwapOutlined />}
            onClick={() => {
              // 跳详情页带 compare query —— T20 detail 页处理
              const [a, b] = compareSelection;
              router.push(
                `/dashboard/eval/runs/${b}?compare_to=${a}`,
              );
            }}
          >
            对比 ({compareSelection.length}/2)
          </Button>
        )}
      </div>

      {/* KPI 行 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {kpiCards.length === 0 && !summaryLoading ? (
          <Col span={24}>
            <Card>
              <Empty description="还没有 run 数据,点「新建评测」开始" />
            </Card>
          </Col>
        ) : (
          kpiCards.map((kpi, idx) => (
            <Col xs={24} sm={12} md={6} key={idx}>
              <Card size="small" loading={summaryLoading}>
                <Statistic
                  title={kpi.label}
                  value={kpi.value}
                  valueStyle={{ fontSize: 22 }}
                />
                {kpi.delta && (
                  <div
                    style={{
                      fontSize: 12,
                      color: KPI_TONE_COLOR[kpi.deltaTone ?? "neutral"],
                      marginTop: 4,
                    }}
                  >
                    {kpi.delta}
                  </div>
                )}
                {kpi.hint && (
                  <div
                    style={{
                      fontSize: 11,
                      color: "#999",
                      marginTop: 2,
                    }}
                  >
                    {kpi.hint}
                  </div>
                )}
              </Card>
            </Col>
          ))
        )}
        {/* 上次对比 KPI(若有) */}
        {latestCompare && (
          <Col xs={24} sm={12} md={6}>
            <Card size="small" title="上次对比 / Latest Compare">
              <Statistic
                title="Hit@5 Δ (B − A)"
                value={
                  latestCompare.hit_at_5_delta >= 0
                    ? `+${latestCompare.hit_at_5_delta.toFixed(3)}`
                    : latestCompare.hit_at_5_delta.toFixed(3)
                }
                valueStyle={{
                  color:
                    latestCompare.hit_at_5_delta > 0
                      ? "#3f8600"
                      : latestCompare.hit_at_5_delta < 0
                        ? "#cf1322"
                        : "#999",
                  fontSize: 22,
                }}
              />
              <div style={{ fontSize: 11, color: "#999", marginTop: 4 }}>
                A #{latestCompare.run_id_a} vs B #{latestCompare.run_id_b} ·{" "}
                {latestCompare.winner_counts.a}A胜 / {latestCompare.winner_counts.b}B胜 /{" "}
                {latestCompare.winner_counts.tie}平
              </div>
            </Card>
          </Col>
        )}
      </Row>

      {/* 趋势图 */}
      <div style={{ marginBottom: 16 }}>
        <TrendLineChart
          series={summary?.trend ?? []}
          metric="hit_at_5"
          title="最近 30 天 Hit@5 趋势(按 dataset 拆线)"
        />
      </div>

      {/* Run 列表 */}
      <Card
        title="最近 Run"
        size="small"
        extra={
          <Tooltip title="勾选 2 个 completed run 后点顶部「对比」按钮">
            <Tag color="blue">{compareSelection.length}/2 已选</Tag>
          </Tooltip>
        }
      >
        <Table<EvalRunListItem>
          rowKey="id"
          loading={summaryLoading}
          dataSource={summary?.recent_runs ?? []}
          columns={runColumns}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          scroll={{ x: 1100 }}
          locale={{
            emptyText: (
              <Empty description="还没有 run,点右上「新建评测」" />
            ),
          }}
        />
      </Card>

      {/* 新建评测 modal:dataset 下拉 + RunConfigForm */}
      <Modal
        title="启动新评测"
        open={startOpen}
        onCancel={() => setStartOpen(false)}
        footer={null}
        destroyOnClose
        width={680}
      >
        <DatasetAndConfigPicker
          datasets={dsData?.items ?? []}
          submitting={startMut.isPending}
          onSubmit={async (datasetId, config) => {
            await startMut.mutateAsync({
              dataset_id: datasetId,
              config,
            });
          }}
        />
      </Modal>
    </div>
  );
}

// ===========================================================================
// 子组件:dataset picker + RunConfigForm 联动
// ===========================================================================

interface DatasetAndConfigPickerProps {
  datasets: EvalDatasetListItem[];
  submitting: boolean;
  onSubmit: (datasetId: number, config: EvalRunConfig) => Promise<void>;
}

function DatasetAndConfigPicker({
  datasets,
  submitting,
  onSubmit,
}: DatasetAndConfigPickerProps) {
  const [form] = Form.useForm<{ dataset_id: number }>();
  const datasetId = Form.useWatch("dataset_id", form);

  const selectedDs = datasets.find((d) => d.id === datasetId);

  // dataset detail 拿 kb_id(列表只有 summary);再 get KB 拿 embedding_model_config_id
  const { data: dsDetail } = useQuery<EvalDatasetDetail | null>({
    queryKey: ["eval-dataset-detail", datasetId],
    queryFn: async () => {
      if (!datasetId) return null;
      return getDataset(datasetId);
    },
    enabled: Boolean(datasetId),
  });

  const { data: kbData } = useQuery<{ embedding_model_config_id: number } | null>({
    queryKey: ["knowledge-base-by-id", dsDetail?.kb_id],
    queryFn: async () => {
      if (!dsDetail?.kb_id) return null;
      const res = await knowledgeApi.get(dsDetail.kb_id);
      const kb = res.data.data;
      if (!kb) return null;
      // KB 类型在 types/api.ts;这里取 embedding_model_config_id 字段
      return kb as unknown as { embedding_model_config_id: number };
    },
    enabled: Boolean(dsDetail?.kb_id),
  });

  // KB 详情还在路上时先不传值,RunConfigForm 内部 effect 等 KB 返回后
  // 单字段更新。不能 ?? 1 —— dev DB id=1 是 MiniMax chat 不是 embedding,
  // 后端 EvalRunCreate 会 500。
  const embeddingModelConfigId = kbData?.embedding_model_config_id;

  return (
    <>
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item
          label="Dataset"
          name="dataset_id"
          rules={[{ required: true, message: "请选 dataset" }]}
        >
          <Select
            placeholder="选一个 dataset"
            showSearch
            optionFilterProp="label"
            options={datasets.map((d) => ({
              value: d.id,
              label: `${d.name} (#${d.id})${
                d.tenant_id === null ? " · builtin" : ""
              }`,
            }))}
          />
        </Form.Item>
      </Form>

      {selectedDs ? (
        <RunConfigForm
          open
          onCancel={() => undefined}
          onSubmit={async (payload) => {
            await onSubmit(selectedDs.id, payload);
          }}
          defaultEmbeddingModelConfigId={embeddingModelConfigId}
          submitting={submitting}
        />
      ) : (
        <Card>
          <Empty description="选个 dataset 后才能配 Run 参数" />
        </Card>
      )}
    </>
  );
}

// ===========================================================================
// 备注(开发自检):
//
// - 趋势 / KPI 都基于 EvalDashboardSummary(前端客户端聚合)。
// - 没有 chart 库时,TrendLineChart 已经做了 sparkline + Table。
// - buildKPICards / computeKPIRaw 暴露在 services/eval.ts 顶层,测试可单测。
// - 上次对比 KPI 直接复用 summary.latest_compare;compareSelection 控制进入
//   详情页带 ?compare_to=A_id。
// ===========================================================================
