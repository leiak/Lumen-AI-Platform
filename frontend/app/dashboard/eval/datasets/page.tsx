"use client";

// frontend/app/dashboard/eval/datasets/page.tsx
// M37.1 — /dashboard/eval/datasets list page.
//
// 列表 + 新建 dataset 按钮 + 删除按钮 + 「跑评测集」占位按钮。
// 「批量导入 items」按钮:在行级 Tooltip 内跳到 detail 页 items tab(M37.1
// 暂未在 detail 页加 tab,先跳到 /detail/{id} 即可)。
//
// 列表列:
//   - name(链接到 detail 页)
//   - KB id(纯展示,后续接 KB 名 lookup)
//   - source Tag
//   - builtin Tag(tenant_id == null 时显示)
//   - is_active Tag(启用 / 停用)
//   - item_count
//   - created_at
//   - 操作:跑评测 / 删除 / 「批量导入 items」

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
  type EvalDatasetListResult,
} from "@/services/eval_dataset";
import type {
  EvalDatasetCreate,
  EvalDatasetListItem,
  EvalDatasetSource,
} from "@/types/eval_dataset";
import DatasetForm from "@/components/eval/DatasetForm";

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
          <Tooltip title="评测运行器开发中(M37.2 完工后启用)">
            <Button
              type="link"
              size="small"
              icon={<ThunderboltOutlined />}
              disabled
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
    </div>
  );
}