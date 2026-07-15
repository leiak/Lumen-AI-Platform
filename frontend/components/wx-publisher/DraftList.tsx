// frontend/components/wx-publisher/DraftList.tsx
// M32 — 公众号助手 — 草稿列表 (Table).
//
// Spec §5.2 — AntD Table 服务端分页 + 状态过滤 + 状态 Tag 颜色.
"use client";

import { useMemo } from "react";
import { Table, Tag, Button, Space, Tooltip } from "antd";
import {
  EditOutlined,
  CopyOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import type { WxDraftListItem, WxDraftStatus } from "@/types/wx-publisher";

const STATUS_COLOR: Record<string, string> = {
  draft: "default",
  rendering: "processing",
  ready: "cyan",
  publishing: "blue",
  published: "success",
  failed: "error",
};

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  rendering: "排版中",
  ready: "待发布",
  publishing: "发布中",
  published: "已发布",
  failed: "失败",
};

interface DraftListProps {
  items: WxDraftListItem[];
  loading?: boolean;
  total?: number;
  page?: number;
  pageSize?: number;
  onPageChange?: (page: number, pageSize: number) => void;
  onEdit?: (id: number) => void;
  onDuplicate?: (id: number) => void;
  onDelete?: (id: number) => void;
}

export function DraftList({
  items,
  loading,
  total = 0,
  page = 1,
  pageSize = 10,
  onPageChange,
  onEdit,
  onDuplicate,
  onDelete,
}: DraftListProps) {
  // 状态过滤下拉选项 — 6 个状态.
  const statusFilters = useMemo(
    () =>
      Object.entries(STATUS_LABEL).map(([value, text]) => ({
        text,
        value,
      })),
    []
  );

  return (
    <Table<WxDraftListItem>
      rowKey="id"
      dataSource={items}
      loading={loading}
      pagination={{
        current: page,
        pageSize,
        total,
        showSizeChanger: true,
        showTotal: (t) => `共 ${t} 条`,
        onChange: onPageChange,
      }}
      locale={{ emptyText: "暂无草稿" }}
      columns={[
        {
          title: "标题",
          dataIndex: "title",
          key: "title",
          ellipsis: true,
        },
        {
          title: "状态",
          dataIndex: "status",
          key: "status",
          width: 100,
          filters: statusFilters,
          onFilter: (value, row) => row.status === value,
          render: (v: string) => (
            <Tag color={STATUS_COLOR[v] ?? "default"}>
              {STATUS_LABEL[v] ?? v}
            </Tag>
          ),
        },
        {
          title: "模板",
          dataIndex: "template_id",
          key: "template_id",
          width: 80,
          render: (v: number | null) =>
            v ? <span>#{v}</span> : <span style={{ color: "#bbb" }}>—</span>,
        },
        {
          title: "账号",
          dataIndex: "account_id",
          key: "account_id",
          width: 80,
          render: (v: number | null) =>
            v ? <span>#{v}</span> : <span style={{ color: "#bbb" }}>—</span>,
        },
        {
          title: "更新时间",
          dataIndex: "updated_at",
          key: "updated_at",
          width: 170,
          render: (v: string) => (
            <span style={{ fontSize: 12, color: "#888" }}>
              {new Date(v).toLocaleString()}
            </span>
          ),
        },
        {
          title: "操作",
          key: "actions",
          width: 140,
          render: (_, row) => (
            <Space size={4}>
              {onEdit && (
                <Tooltip title="编辑">
                  <Button
                    type="link"
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => onEdit(row.id)}
                  >
                    编辑
                  </Button>
                </Tooltip>
              )}
              {onDuplicate && (
                <Tooltip title="复制">
                  <Button
                    type="link"
                    size="small"
                    icon={<CopyOutlined />}
                    onClick={() => onDuplicate(row.id)}
                  />
                </Tooltip>
              )}
              {onDelete && (
                <Tooltip title="删除">
                  <Button
                    type="link"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => onDelete(row.id)}
                  />
                </Tooltip>
              )}
            </Space>
          ),
        },
      ]}
    />
  );
}

export default DraftList;