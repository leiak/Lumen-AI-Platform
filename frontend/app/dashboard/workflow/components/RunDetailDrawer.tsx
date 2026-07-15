"use client";

import { Drawer, Tag, Alert, Space, Table } from "antd";
import { WorkflowRun, WorkflowNodeRun } from "@/services/workflow";

interface Props {
  open: boolean;
  run: WorkflowRun | null;
  nodeRuns: WorkflowNodeRun[];
  loading: boolean;
  onClose: () => void;
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
 * M30b: per-run detail. The node-runs table is the M30a story —
 * each row is one WorkflowNodeRun record (running → completed /
 * failed, with input_data, output_data, error_message).
 */
export function RunDetailDrawer({ open, run, nodeRuns, loading, onClose }: Props) {
  return (
    <Drawer
      title={`执行详情 — Run #${run?.id ?? ""}`}
      open={open}
      onClose={onClose}
      width={640}
    >
      {run ? (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Space wrap>
            <span>
              状态: <Tag color={statusColor(run.status)}>{run.status}</Tag>
            </span>
            <span>
              触发:{" "}
              {run.trigger_source === "scheduled" ? (
                <Tag color="blue">定时</Tag>
              ) : (
                <Tag>手动</Tag>
              )}
            </span>
            <span>
              开始:{" "}
              {run.started_at ? new Date(run.started_at).toLocaleString() : "-"}
            </span>
            <span>
              结束:{" "}
              {run.finished_at ? new Date(run.finished_at).toLocaleString() : "-"}
            </span>
          </Space>
          {run.status === "failed" && run.error_message && (
            <Alert
              type="error"
              showIcon
              message="执行失败"
              description={run.error_message}
            />
          )}
          {run.output_data && (
            <div>
              <div style={{ fontWeight: 500, marginBottom: 6 }}>输出</div>
              <pre
                style={{
                  whiteSpace: "pre-wrap",
                  background: "#fafafa",
                  padding: 8,
                  borderRadius: 4,
                  fontSize: 12,
                  maxHeight: 240,
                  overflow: "auto",
                }}
              >
                {JSON.stringify(run.output_data, null, 2)}
              </pre>
            </div>
          )}
          <div>
            <div style={{ fontWeight: 500, marginBottom: 6 }}>
              节点执行(M30a)
            </div>
            <Table
              rowKey="id"
              size="small"
              loading={loading}
              dataSource={nodeRuns}
              pagination={false}
              locale={{
                emptyText: loading ? "加载中…" : "无节点记录",
              }}
              columns={[
                {
                  title: "顺序",
                  dataIndex: "execution_order",
                  key: "execution_order",
                  width: 60,
                },
                {
                  title: "节点",
                  dataIndex: "node_id",
                  key: "node_id",
                  width: 140,
                  ellipsis: true,
                },
                {
                  title: "类型",
                  dataIndex: "node_type",
                  key: "node_type",
                  width: 90,
                  render: (v: string) => <Tag>{v}</Tag>,
                },
                {
                  title: "状态",
                  dataIndex: "status",
                  key: "status",
                  width: 90,
                  render: (v: string) => <Tag color={statusColor(v)}>{v}</Tag>,
                },
                {
                  title: "耗时",
                  key: "node_duration",
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
          </div>
        </Space>
      ) : (
        <div style={{ color: "#999" }}>未选择 Run</div>
      )}
    </Drawer>
  );
}
