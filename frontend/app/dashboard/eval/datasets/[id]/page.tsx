"use client";

// frontend/app/dashboard/eval/datasets/[id]/page.tsx
// M37.1 — 详情页:dataset info card + items table + 加 item / 批量导入 / 删单条。
//
// 顶部 card:dataset 元数据(name / KB / source / builtin 标 / 创建者 / 时间)
// 中部:ItemTable,每行可编辑 / 删除
// 工具栏:返回列表 + 加 item + 批量导入 + 删除 dataset
//
// 注意:detail 没有更新 dataset 字段的入口(plan 没要求;若需要再加一个
// DatasetFormModal 复用 DatasetForm 加 edit mode 即可)。

import { useState } from "react";
import {
  Button,
  Card,
  Space,
  Tag,
  Descriptions,
  Popconfirm,
  App,
  Skeleton,
} from "antd";
import {
  ArrowLeftOutlined,
  PlusOutlined,
  UploadOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import {
  getDataset,
  deleteDataset,
  listItems,
  addItem,
  deleteItem,
} from "@/services/eval_dataset";
import type {
  EvalDatasetItem,
  EvalDatasetItemCreate,
  EvalDatasetDetail,
  EvalDatasetItemListResult,
  EvalDatasetSource,
} from "@/types/eval_dataset";
import ItemTable from "@/components/eval/ItemTable";
import ItemFormModal from "@/components/eval/ItemFormModal";
import BulkImportModal from "@/components/eval/BulkImportModal";

const SOURCE_LABELS: Record<EvalDatasetSource, string> = {
  manual: "手动",
  imported: "导入",
  synthetic: "合成",
};

export default function EvalDatasetDetailPage() {
  // 跟 wx-publisher/drafts/[id] 一致:用 next/navigation 的 useParams() 拿路由参数。
  // 项目 React 还是 18.3(不是 19),不能 use() 解 Promise<params>。
  const params = useParams<{ id: string }>();
  const datasetId = Number(params.id);
  const router = useRouter();
  const qc = useQueryClient();
  const { message } = App.useApp();

  const [itemFormOpen, setItemFormOpen] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);

  const {
    data: dataset,
    isLoading: dsLoading,
  } = useQuery<EvalDatasetDetail>({
    queryKey: ["eval-datasets", datasetId],
    queryFn: () => getDataset(datasetId),
    enabled: Number.isFinite(datasetId),
  });

  const {
    data: itemsData,
    isLoading: itemsLoading,
    refetch: refetchItems,
  } = useQuery<EvalDatasetItemListResult>({
    queryKey: ["eval-datasets", datasetId, "items"],
    queryFn: () => listItems(datasetId, { page: 1, page_size: 200 }),
    enabled: Number.isFinite(datasetId),
  });

  const deleteDatasetMut = useMutation({
    mutationFn: () => deleteDataset(datasetId),
    onSuccess: () => {
      message.success("已删除 dataset");
      qc.invalidateQueries({ queryKey: ["eval-datasets"] });
      router.push("/dashboard/eval/datasets");
    },
    onError: (e: Error) => message.error(`删除失败:${e.message}`),
  });

  const addItemMut = useMutation({
    mutationFn: (payload: EvalDatasetItemCreate) => addItem(datasetId, payload),
    onSuccess: () => {
      message.success("已加一条 item");
      setItemFormOpen(false);
      qc.invalidateQueries({
        queryKey: ["eval-datasets", datasetId, "items"],
      });
      // 列表页 item_count 也需要刷新
      qc.invalidateQueries({ queryKey: ["eval-datasets"] });
    },
    onError: (e: Error) => message.error(`新增失败:${e.message}`),
  });

  const deleteItemMut = useMutation({
    mutationFn: (itemId: number) => deleteItem(datasetId, itemId),
    onSuccess: () => {
      message.success("已删除 item");
      qc.invalidateQueries({
        queryKey: ["eval-datasets", datasetId, "items"],
      });
      qc.invalidateQueries({ queryKey: ["eval-datasets"] });
    },
    onError: (e: Error) => message.error(`删除失败:${e.message}`),
  });

  if (dsLoading) {
    return (
      <div style={{ padding: 24 }}>
        <Skeleton active />
      </div>
    );
  }
  if (!dataset) {
    return (
      <div style={{ padding: 24 }}>
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() => router.push("/dashboard/eval/datasets")}
        >
          返回列表
        </Button>
        <p style={{ marginTop: 16, color: "#999" }}>dataset 不存在或已被删除</p>
      </div>
    );
  }

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16 }}>
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() => router.push("/dashboard/eval/datasets")}
        >
          返回列表
        </Button>
      </Space>

      <Card
        title={
          <Space>
            <span>{dataset.name}</span>
            <Tag color="blue">{SOURCE_LABELS[dataset.source]}</Tag>
            {dataset.tenant_id === null && (
              <Tag color="gold">builtin</Tag>
            )}
            {dataset.is_active === 1 ? (
              <Tag color="green">启用</Tag>
            ) : (
              <Tag color="default">停用</Tag>
            )}
          </Space>
        }
        extra={
          <Space>
            <Popconfirm
              title="确定删除此 dataset?所有 items 也会一并删除。"
              okText="删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={() => deleteDatasetMut.mutate()}
            >
              <Button danger icon={<DeleteOutlined />}>
                删除 dataset
              </Button>
            </Popconfirm>
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <Descriptions column={2} size="small">
          <Descriptions.Item label="Dataset ID">#{dataset.id}</Descriptions.Item>
          <Descriptions.Item label="KB">
            <Tag color="blue">#{dataset.kb_id}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Items 数">
            {dataset.item_count ?? 0}
          </Descriptions.Item>
          <Descriptions.Item label="Tenant ID">
            {dataset.tenant_id === null ? "— (builtin)" : dataset.tenant_id}
          </Descriptions.Item>
          <Descriptions.Item label="创建者">
            {dataset.created_by ?? "—"}
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {new Date(dataset.created_at).toLocaleString("zh-CN")}
          </Descriptions.Item>
          {dataset.description && (
            <Descriptions.Item label="描述" span={2}>
              {dataset.description}
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      <Card
        title={`Items (${itemsData?.total ?? 0})`}
        extra={
          <Space>
            <Button
              icon={<UploadOutlined />}
              onClick={() => setBulkOpen(true)}
            >
              批量导入
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setItemFormOpen(true)}
            >
              加 item
            </Button>
          </Space>
        }
      >
        <ItemTable
          items={itemsData?.items ?? []}
          loading={itemsLoading}
          onEdit={(it: EvalDatasetItem) => {
            // M37.1 后端没有 update item endpoint,先提示。
            message.info(
              "M37.1 暂未开放编辑单条 item;如需修改请先删除再加。",
            );
          }}
          onDelete={async (it) => {
            await deleteItemMut.mutateAsync(it.id);
          }}
        />
      </Card>

      <ItemFormModal
        open={itemFormOpen}
        onCancel={() => setItemFormOpen(false)}
        onSubmit={async (payload) => {
          await addItemMut.mutateAsync(payload);
        }}
        submitting={addItemMut.isPending}
      />

      <BulkImportModal
        open={bulkOpen}
        datasetId={datasetId}
        onCancel={() => setBulkOpen(false)}
        onSuccess={() => {
          qc.invalidateQueries({
            queryKey: ["eval-datasets", datasetId, "items"],
          });
          qc.invalidateQueries({ queryKey: ["eval-datasets"] });
        }}
      />
    </div>
  );
}