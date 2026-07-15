"use client";

import { Space, Button, Table, Tag, Popconfirm, Tooltip } from "antd";
import {
  ToolOutlined,
  ClockCircleOutlined,
  HistoryOutlined,
  CloudUploadOutlined,
  PlayCircleOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useRouter } from "next/navigation";
import { Workflow } from "@/services/workflow";

interface Props {
  workflows: Workflow[];
  loading: boolean;
  page: number;
  pageSize: number;
  total: number;
  runningId: number | null;
  publishingId: number | null;
  onPageChange: (page: number, pageSize: number) => void;
  onRun: (id: number) => void;
  onEditSchedules: (id: number) => void;
  onViewHistory: (id: number, name: string) => void;
  onPublishTemplate: (id: number) => void;
  onDelete: (id: number) => void;
}

/**
 * M30b: workflow list table.
 *
 * Pure presentation — all data + side effects come from the page
 * (or its hooks). Keeping the table dumb makes the row actions easy
 * to test independently.
 */
export function WorkflowTable({
  workflows,
  loading,
  page,
  pageSize,
  total,
  runningId,
  publishingId,
  onPageChange,
  onRun,
  onEditSchedules,
  onViewHistory,
  onPublishTemplate,
  onDelete,
}: Props) {
  const router = useRouter();

  const columns: ColumnsType<Workflow> = [
    { title: "ID", dataIndex: "id", key: "id", width: 80 },
    { title: "名称", dataIndex: "name", key: "name" },
    { title: "描述", dataIndex: "description", key: "description" },
    {
      title: "状态",
      dataIndex: "is_active",
      key: "is_active",
      render: (active: boolean) => (
        <Tag color={active ? "green" : "red"}>{active ? "启用" : "禁用"}</Tag>
      ),
    },
    { title: "创建时间", dataIndex: "created_at", key: "created_at" },
    {
      title: "操作",
      key: "action",
      width: 380,
      render: (_, record) => (
        <Space wrap>
          <Tooltip title="设计">
            <Button
              size="small"
              icon={<ToolOutlined />}
              onClick={() => router.push(`/dashboard/workflow/designer?id=${record.id}`)}
            />
          </Tooltip>
          <Tooltip title="定时">
            <Button
              size="small"
              icon={<ClockCircleOutlined />}
              onClick={() => onEditSchedules(record.id)}
            />
          </Tooltip>
          <Tooltip title="历史">
            <Button
              size="small"
              icon={<HistoryOutlined />}
              onClick={() => onViewHistory(record.id, record.name)}
            />
          </Tooltip>
          <Tooltip title="发布为模板">
            <Button
              size="small"
              icon={<CloudUploadOutlined />}
              loading={publishingId === record.id}
              onClick={() => onPublishTemplate(record.id)}
            />
          </Tooltip>
          <Tooltip title="执行">
            <Button
              size="small"
              type="primary"
              icon={<PlayCircleOutlined />}
              loading={runningId === record.id}
              onClick={() => onRun(record.id)}
            />
          </Tooltip>
          <Popconfirm
            title="确认删除?"
            description="删除工作流会同时删除其运行历史。"
            okText="删除"
            cancelText="取消"
            onConfirm={() => onDelete(record.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Table
      columns={columns}
      dataSource={workflows}
      rowKey="id"
      loading={loading}
      pagination={{
        current: page,
        pageSize,
        total,
        showSizeChanger: true,
        showTotal: (t) => `共 ${t} 条`,
        onChange: onPageChange,
      }}
    />
  );
}
