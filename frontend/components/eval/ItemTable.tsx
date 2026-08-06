"use client";

// frontend/components/eval/ItemTable.tsx
// M37.1 — Items table for the dataset detail page.
//
// Columns:
//   - query (text)
//   - expected_doc_ids (前 3 个 + Tag.N+"more",整列可 tooltip 展开)
//   - expected_answer (前 60 字 + 「展开」Typography.Paragraph)
//   - category Tag (5 色映射)
//   - difficulty Tag (3 色映射)
//   - 操作:编辑 / 删除
//
// 数据来源:父组件传入 EvalDatasetItem[] + 回调。M37.1 后端没有 GET /items
// 分页 endpoint(只测了 1 万以下的小数据集 OK),items 列表在父组件走 list_items
// service 或通过 dataset detail 拿全。

import { Table, Tag, Button, Popconfirm, Space, Tooltip } from "antd";
import {
  DeleteOutlined,
  EditOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type {
  EvalDatasetItem,
  EvalDatasetCategory,
  EvalDatasetDifficulty,
} from "@/types/eval_dataset";

interface ItemTableProps {
  items: EvalDatasetItem[];
  loading?: boolean;
  onEdit: (item: EvalDatasetItem) => void;
  onDelete: (item: EvalDatasetItem) => void | Promise<void>;
}

// 5 类 category → Tag 颜色(让用户一眼分清样本类型)
const CATEGORY_COLORS: Record<EvalDatasetCategory, string> = {
  factual: "blue",
  reasoning: "purple",
  multi_hop: "magenta",
  keyword_heavy: "cyan",
  out_of_scope: "default",
};

const CATEGORY_LABELS: Record<EvalDatasetCategory, string> = {
  factual: "事实",
  reasoning: "推理",
  multi_hop: "多跳",
  keyword_heavy: "关键词",
  out_of_scope: "越界",
};

const DIFFICULTY_COLORS: Record<EvalDatasetDifficulty, string> = {
  easy: "green",
  medium: "gold",
  hard: "red",
};

const DIFFICULTY_LABELS: Record<EvalDatasetDifficulty, string> = {
  easy: "简单",
  medium: "中等",
  hard: "困难",
};

export default function ItemTable({
  items,
  loading,
  onEdit,
  onDelete,
}: ItemTableProps) {
  const columns: ColumnsType<EvalDatasetItem> = [
    {
      title: "Query",
      dataIndex: "query",
      key: "query",
      width: 280,
      ellipsis: { showTitle: true },
      render: (q: string) => (
        <Tooltip title={q}>
          <span style={{ fontFamily: "monospace" }}>{q}</span>
        </Tooltip>
      ),
    },
    {
      title: "期望文档",
      dataIndex: "expected_doc_ids",
      key: "expected_doc_ids",
      width: 140,
      render: (ids: number[]) => {
        if (!ids || ids.length === 0) {
          return <span style={{ color: "#999" }}>—</span>;
        }
        const head = ids.slice(0, 3);
        const rest = ids.length - head.length;
        return (
          <Space size={2} wrap>
            {head.map((id) => (
              <Tag key={id} color="blue">
                #{id}
              </Tag>
            ))}
            {rest > 0 && <Tag color="default">+{rest}</Tag>}
          </Space>
        );
      },
    },
    {
      title: "期望答案",
      dataIndex: "expected_answer",
      key: "expected_answer",
      ellipsis: true,
      width: 280,
      render: (ans: string | null) =>
        ans ? (
          <Tooltip title={ans}>
            <span style={{ color: "#444" }}>{ans}</span>
          </Tooltip>
        ) : (
          <span style={{ color: "#999" }}>—</span>
        ),
    },
    {
      title: "分类",
      dataIndex: "category",
      key: "category",
      width: 90,
      render: (c: EvalDatasetCategory | null) =>
        c ? (
          <Tag color={CATEGORY_COLORS[c]}>{CATEGORY_LABELS[c]}</Tag>
        ) : (
          <span style={{ color: "#999" }}>—</span>
        ),
    },
    {
      title: "难度",
      dataIndex: "difficulty",
      key: "difficulty",
      width: 80,
      render: (d: EvalDatasetDifficulty | null) =>
        d ? (
          <Tag color={DIFFICULTY_COLORS[d]}>{DIFFICULTY_LABELS[d]}</Tag>
        ) : (
          <span style={{ color: "#999" }}>—</span>
        ),
    },
    {
      title: "操作",
      key: "actions",
      width: 130,
      fixed: "right",
      render: (_, item) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => onEdit(item)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定删除此 item?"
            okText="删除"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            onConfirm={() => onDelete(item)}
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
    <Table<EvalDatasetItem>
      rowKey="id"
      size="middle"
      loading={loading}
      dataSource={items}
      columns={columns}
      pagination={{ pageSize: 20, showSizeChanger: true }}
      scroll={{ x: 900 }}
    />
  );
}