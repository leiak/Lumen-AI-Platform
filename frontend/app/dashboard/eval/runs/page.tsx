"use client";

// frontend/app/dashboard/eval/runs/page.tsx
// M37.3 — 评测运行列表页 (RAG 评测 → 评测运行)。
//
// 跟 /dashboard/eval (看板) 的 run table 区别:
//   - 看板的 table 是 dashboard 一部分,顺手列出最近 run + 进度 chip + 取消按钮,
//     用来对比一段时间趋势;
//   - 这一页是完整的「评测运行」管理列表 — 全量分页 + dataset / status
//     filter,覆盖历史 + 当前 run,运营 / 算法想看某个 dataset 的所有
//     run 历史时来这里。
//
// 跟 /dashboard/eval/datasets/[id] 的区别:数据集详情页只列该 dataset 的
// runs (用 dataset_id filter);这一页全量,可按需 filter dataset。
//
// row click → /dashboard/eval/runs/{id} 详情页。

import { useState } from "react";
import {
  Button,
  Space,
  Table,
  Tag,
  Tooltip,
  Popconfirm,
  App,
  Select,
  InputNumber,
  Empty,
  Card,
  Row,
  Col,
} from "antd";
import { ReloadOutlined, ArrowLeftOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { listRuns, cancelRun } from "@/services/eval_run";
import type {
  EvalRunCancel,
  EvalRunListItem,
  EvalRunListParams,
  EvalRunStatus,
} from "@/types/eval_run";

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

const STATUS_OPTIONS = (Object.keys(STATUS_LABEL) as EvalRunStatus[]).map(
  (s) => ({ value: s, label: STATUS_LABEL[s] }),
);

export default function EvalRunsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const { message } = App.useApp();

  // filters — 控制 listRuns 入参 + 触发 refetch
  const [filterStatus, setFilterStatus] = useState<EvalRunStatus | null>(null);
  const [filterDatasetId, setFilterDatasetId] = useState<number | null>(null);

  const listParams: EvalRunListParams = {
    page: 1,
    page_size: 100,
    ...(filterStatus ? { status: filterStatus } : {}),
    ...(filterDatasetId !== null ? { dataset_id: filterDatasetId } : {}),
  };

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["eval-runs", listParams],
    queryFn: () => listRuns(listParams),
  });

  const cancelMut = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload?: EvalRunCancel }) =>
      cancelRun(id, payload),
    onSuccess: (run) => {
      message.success(`已取消 Run #${run.id}`);
      qc.invalidateQueries({ queryKey: ["eval-runs"] });
    },
    onError: (e: Error) => message.error(`取消失败:${e.message}`),
  });

  const columns: ColumnsType<EvalRunListItem> = [
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
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 90,
      render: (s: EvalRunStatus) => (
        <Tag color={STATUS_COLOR[s]}>{STATUS_LABEL[s]}</Tag>
      ),
    },
    {
      title: "进度",
      key: "progress",
      width: 160,
      render: (_, row) => {
        const done = row.completed_items ?? 0;
        const total = row.total_items ?? 0;
        const pct = total > 0 ? Math.round((done / total) * 100) : 0;
        return (
          <Tooltip title={`${done} / ${total}`}>
            <span>
              {done} / {total}{" "}
              <span style={{ color: "#999" }}>({pct}%)</span>
            </span>
          </Tooltip>
        );
      },
    },
    {
      title: "耗时",
      key: "duration",
      width: 110,
      render: (_, row) => {
        if (!row.started_at) return <Tag>未开始</Tag>;
        const start = new Date(row.started_at).getTime();
        const end = row.finished_at
          ? new Date(row.finished_at).getTime()
          : Date.now();
        const ms = end - start;
        if (ms < 0) return "—";
        const s = Math.round(ms / 1000);
        if (s < 60) return `${s}s`;
        const m = Math.floor(s / 60);
        return `${m}m ${s % 60}s`;
      },
    },
    {
      title: "开始时间",
      dataIndex: "started_at",
      key: "started_at",
      width: 170,
      render: (s: string | null) =>
        s ? (
          new Date(s).toLocaleString("zh-CN")
        ) : (
          <Tag>未开始</Tag>
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
      title: "操作",
      key: "actions",
      width: 140,
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
                cancelMut.mutate({
                  id: row.id,
                  payload: { reason: "用户在运行列表取消" },
                })
              }
            >
              <Button type="link" size="small" danger>
                取消
              </Button>
            </Popconfirm>
          )}
          <Button
            type="link"
            size="small"
            onClick={() => router.push(`/dashboard/eval/runs/${row.id}`)}
          >
            详情
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
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
        <h2 style={{ margin: 0, marginRight: "auto" }}>评测运行</h2>
        <Button icon={<ReloadOutlined />} onClick={() => refetch()}>
          刷新
        </Button>
      </div>

      {/* Filter bar — 跟 listParams 绑在一起,改一个触发 refetch */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col>
            <span style={{ marginRight: 8 }}>状态:</span>
            <Select
              allowClear
              placeholder="全部"
              style={{ width: 140 }}
              value={filterStatus}
              onChange={(v) => setFilterStatus(v ?? null)}
              options={STATUS_OPTIONS}
            />
          </Col>
          <Col>
            <span style={{ marginRight: 8 }}>Dataset ID:</span>
            <InputNumber
              placeholder="如 57"
              value={filterDatasetId ?? undefined}
              onChange={(v) => setFilterDatasetId(v ?? null)}
              min={1}
              style={{ width: 140 }}
            />
          </Col>
          <Col>
            <Button
              size="small"
              onClick={() => {
                setFilterStatus(null);
                setFilterDatasetId(null);
              }}
            >
              清空筛选
            </Button>
          </Col>
        </Row>
      </Card>

      <Table<EvalRunListItem>
        rowKey="id"
        size="middle"
        loading={isLoading}
        columns={columns}
        dataSource={data?.items ?? []}
        locale={{
          emptyText: (
            <Empty description="还没有 run,从「评测数据集」挑一个 dataset 启动" />
          ),
        }}
        scroll={{ x: 1100 }}
        pagination={{
          total: data?.total ?? 0,
          pageSize: data?.page_size ?? 20,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
        }}
      />
    </div>
  );
}
