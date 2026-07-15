"use client";

import { Drawer, Table, Tag } from "antd";
import { WorkflowRun } from "@/services/workflow";

interface Props {
  open: boolean;
  workflowName: string;
  runs: WorkflowRun[];
  loading: boolean;
  page: number;
  pageSize: number;
  total: number;
  onClose: () => void;
  onPageChange: (page: number, pageSize: number) => void;
  onSelectRun: (run: WorkflowRun) => void;
}

const statusColor = (status: string) =>
  status === "completed"
    ? "green"
    : status === "failed"
      ? "red"
      : status === "running"
        ? "blue"
        : "default";

const fmtDuration = (started: string | null | undefined, finished: string | null | undefined) => {
  if (!started || !finished) return "-";
  const ms = new Date(finished).getTime() - new Date(started).getTime();
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`;
  return `${(ms / 60_000).toFixed(2)} min`;
};

/**
 * M30b: paginated run history for one workflow. Clicking a row opens
 * the RunDetailDrawer for that run.
 */
export function RunHistoryDrawer({
  open,
  workflowName,
  runs,
  loading,
  page,
  pageSize,
  total,
  onClose,
  onPageChange,
  onSelectRun,
}: Props) {
  return (
    <Drawer
      title={`执行历史 — ${workflowName || ""}`}
      open={open}
      onClose={onClose}
      width={720}
    >
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={runs}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: onPageChange,
        }}
        onRow={(record) => ({
          onClick: () => onSelectRun(record),
          style: { cursor: "pointer" },
        })}
        columns={[
          { title: "ID", dataIndex: "id", key: "id", width: 60 },
          {
            title: "触发",
            dataIndex: "trigger_source",
            key: "trigger_source",
            width: 80,
            render: (v: string | null | undefined) =>
              v === "scheduled" ? <Tag color="blue">定时</Tag> : <Tag>手动</Tag>,
          },
          {
            title: "状态",
            dataIndex: "status",
            key: "status",
            width: 90,
            render: (v: string) => <Tag color={statusColor(v)}>{v}</Tag>,
          },
          {
            title: "开始",
            dataIndex: "started_at",
            key: "started_at",
            width: 160,
            render: (v: string | null | undefined) =>
              v ? new Date(v).toLocaleString() : "-",
          },
          {
            title: "耗时",
            key: "duration",
            width: 80,
            render: (_, r) => fmtDuration(r.started_at, r.finished_at),
          },
          {
            title: "错误",
            dataIndex: "error_message",
            key: "error_message",
            ellipsis: true,
            render: (v: string | null | undefined) =>
              v ? <span style={{ color: "#cf1322" }}>{v}</span> : "-",
          },
        ]}
      />
    </Drawer>
  );
}
