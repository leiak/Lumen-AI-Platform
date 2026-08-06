"use client";

// frontend/app/dashboard/eval/datasets/page.tsx
// M37.1 / M37.2 follow-up — /dashboard/eval/datasets list page.
//
// 列表 + 新建 dataset 按钮 + 删除按钮 + 行级「跑这个评测集」按钮
// (点击后弹 RunConfigForm,提交后跳 /dashboard/eval/runs/{id} 看实时进度)。
//
// 列表列:
//   - name(链接到 detail 页)
//   - KB id(纯展示,后续接 KB 名 lookup)
//   - source Tag
//   - builtin Tag(tenant_id == null 时显示)
//   - is_active Tag(启用 / 停用)
//   - item_count
//   - created_at
//   - 操作:跑这个评测集 / 管理 items / 删除

import { useState } from "react";
import {
  Button,
  Space,
  Table,
  Tag,
  Tooltip,
  Popconfirm,
  Empty,
  App,
} from "antd";
import {
  PlusOutlined,
  ReloadOutlined,
  DeleteOutlined,
  ThunderboltOutlined,
  PlayCircleOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  listDatasets,
  createDataset,
  deleteDataset,
  getDataset,
} from "@/services/eval_dataset";
import { startRun } from "@/services/eval_run";
import { knowledgeApi } from "@/services/knowledge";
import type { EvalDatasetListResult } from "@/services/eval_dataset";
import type {
  EvalDatasetCreate,
  EvalDatasetDetail,
  EvalDatasetListItem,
  EvalDatasetSource,
} from "@/types/eval_dataset";
import type { EvalRunConfig, EvalRunCreate } from "@/types/eval_run";
import DatasetForm from "@/components/eval/DatasetForm";
import RunConfigForm from "@/components/eval/RunConfigForm";

const SOURCE_LABELS: Record<EvalDatasetSource, string> = {
  manual: "手动",
  imported: "导入",
  synthetic: "合成",
};
const SOURCE_COLORS: Record<EvalDatasetSource, string> = {
  manual: "blue",
  imported: "purple",
  synthetic: "cyan",
};

export default function EvalDatasetsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const { message } = App.useApp();

  const [createOpen, setCreateOpen] = useState(false);
  // 启动评测 modal 状态:跑哪个 dataset(row 级点击设这里)
  const [runTarget, setRunTarget] = useState<EvalDatasetListItem | null>(null);

  // 拉目标 dataset 的 kb_id(列表只返 summary)
  const { data: runTargetDetail } = useQuery<EvalDatasetDetail | null>({
    queryKey: ["eval-dataset-detail", runTarget?.id],
    queryFn: () => (runTarget ? getDataset(runTarget.id) : Promise.resolve(null)),
    enabled: Boolean(runTarget),
  });

  // 拿 KB 的 embedding model config id —— RunConfigForm 锁定默认值
  const { data: runTargetKb } = useQuery<{ embedding_model_config_id: number } | null>({
    queryKey: ["knowledge-base-by-id", runTargetDetail?.kb_id],
    queryFn: async () => {
      if (!runTargetDetail?.kb_id) return null;
      const res = await knowledgeApi.get(runTargetDetail.kb_id);
      const kb = res.data.data;
      if (!kb) return null;
      return kb as unknown as { embedding_model_config_id: number };
    },
    enabled: Boolean(runTargetDetail?.kb_id),
  });

  const startMut = useMutation({
    mutationFn: (payload: EvalRunCreate) => startRun(payload),
    onSuccess: (run) => {
      message.success(`已启动 Run #${run.id},跳转详情看实时进度`);
      setRunTarget(null);
      qc.invalidateQueries({ queryKey: ["eval-runs"] });
      // 跳详情页看进度 / 报告
      router.push(`/dashboard/eval/runs/${run.id}`);
    },
    onError: (e: Error) => message.error(`启动失败:${e.message}`),
  });

  const { data, isLoading, refetch } = useQuery<EvalDatasetListResult>({
    queryKey: ["eval-datasets"],
    queryFn: () => listDatasets({ page: 1, page_size: 100 }),
  });

  const createMut = useMutation({
    mutationFn: (payload: EvalDatasetCreate) => createDataset(payload),
    onSuccess: () => {
      message.success("已创建 dataset");
      setCreateOpen(false);
      qc.invalidateQueries({ queryKey: ["eval-datasets"] });
    },
    onError: (e: Error) => message.error(`创建失败:${e.message}`),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteDataset(id),
    onSuccess: () => {
      message.success("已删除 dataset(items 级联删除)");
      qc.invalidateQueries({ queryKey: ["eval-datasets"] });
    },
    onError: (e: Error) => message.error(`删除失败:${e.message}`),
  });

  const columns: ColumnsType<EvalDatasetListItem> = [
    {
      title: "名称",
      dataIndex: "name",
      key: "name",
      render: (name: string, row) => (
        <a
          onClick={(e) => {
            e.preventDefault();
            router.push(`/dashboard/eval/datasets/${row.id}`);
          }}
          href={`/dashboard/eval/datasets/${row.id}`}
        >
          {name}
        </a>
      ),
    },
    {
      title: "KB",
      dataIndex: "kb_id",
      key: "kb_id",
      width: 80,
      render: (id: number) => <Tag color="blue">#{id}</Tag>,
    },
    {
      title: "类型",
      dataIndex: "source",
      key: "source",
      width: 90,
      render: (s: EvalDatasetSource) => (
        <Tag color={SOURCE_COLORS[s]}>{SOURCE_LABELS[s]}</Tag>
      ),
    },
    {
      title: "可见性",
      key: "scope",
      width: 90,
      render: (_, row) =>
        row.tenant_id === null ? (
          <Tooltip title="builtin dataset,所有租户可见">
            <Tag color="gold">builtin</Tag>
          </Tooltip>
        ) : (
          <Tag>本租户</Tag>
        ),
    },
    {
      title: "状态",
      dataIndex: "is_active",
      key: "is_active",
      width: 80,
      render: (v: number) =>
        v === 1 ? (
          <Tag color="green">启用</Tag>
        ) : (
          <Tag color="default">停用</Tag>
        ),
    },
    {
      title: "Items",
      dataIndex: "item_count",
      key: "item_count",
      width: 80,
      render: (n: number | null) => (n ?? 0).toString(),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 180,
      render: (s: string) => new Date(s).toLocaleString("zh-CN"),
    },
    {
      title: "操作",
      key: "actions",
      width: 260,
      fixed: "right",
      render: (_, row) => (
        <Space size="small" wrap>
          <Tooltip
            title={
              (row.item_count ?? 0) > 0
                ? "用当前配置启动一个 run"
                : "dataset 还没有 items,先去详情页加"
            }
          >
            <Button
              type="link"
              size="small"
              icon={<ThunderboltOutlined />}
              disabled={(row.item_count ?? 0) === 0}
              onClick={() => setRunTarget(row)}
            >
              跑这个评测集
            </Button>
          </Tooltip>
          <Button
            type="link"
            size="small"
            icon={<PlayCircleOutlined />}
            onClick={() => router.push(`/dashboard/eval/datasets/${row.id}`)}
          >
            管理 items
          </Button>
          <Popconfirm
            title={`确定删除 dataset「${row.name}」?所有 items 也会级联删除。`}
            okText="删除"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            onConfirm={() => deleteMut.mutate(row.id)}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
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
        <h2 style={{ margin: 0, marginRight: "auto" }}>RAG 评测集</h2>
        <Button icon={<ReloadOutlined />} onClick={() => refetch()}>
          刷新
        </Button>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setCreateOpen(true)}
        >
          新建 dataset
        </Button>
      </div>

      <Table<EvalDatasetListItem>
        rowKey="id"
        loading={isLoading}
        dataSource={data?.items ?? []}
        columns={columns}
        locale={{
          emptyText: (
            <Empty description="还没有 dataset,点右上角「新建 dataset」试试" />
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

      <DatasetForm
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onSubmit={async (payload) => {
          await createMut.mutateAsync(payload);
        }}
        submitting={createMut.isPending}
      />

      {/* 启动评测 modal —— 跟 /dashboard/eval 上的 picker 共享同一个 RunConfigForm,
          这里预填了 dataset_id,所以不需要 dataset 选择器。 */}
      <RunConfigForm
        open={Boolean(runTarget)}
        onCancel={() => setRunTarget(null)}
        onSubmit={async (config: EvalRunConfig) => {
          if (!runTarget) return;
          await startMut.mutateAsync({
            dataset_id: runTarget.id,
            config,
          });
        }}
        // 拉不到 KB → 兜底 1(nomic-embed-text);但 99% 情况拉得到
        defaultEmbeddingModelConfigId={
          runTargetKb?.embedding_model_config_id ?? 1
        }
        submitting={startMut.isPending}
      />
    </div>
  );
}