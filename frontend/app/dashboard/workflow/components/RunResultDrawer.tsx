"use client";

import { Drawer, Tag, Alert, Space } from "antd";
import { WorkflowRun } from "@/services/workflow";

interface Props {
  open: boolean;
  run: WorkflowRun | null;
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

/**
 * M30b: quick "just ran a workflow" result drawer. Shows the run
 * status + output_data JSON. For per-node detail (which is the M30a
 *  use case), open the RunDetailDrawer via the history view.
 */
export function RunResultDrawer({ open, run, onClose }: Props) {
  return (
    <Drawer
      title="工作流执行结果"
      open={open}
      onClose={onClose}
      width={520}
    >
      {run ? (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div>
            <span style={{ marginRight: 8 }}>状态:</span>
            <Tag color={statusColor(run.status)}>{run.status}</Tag>
          </div>
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
                  maxHeight: 320,
                  overflow: "auto",
                }}
              >
                {JSON.stringify(run.output_data, null, 2)}
              </pre>
            </div>
          )}
        </Space>
      ) : (
        <div style={{ color: "#999" }}>正在获取结果…</div>
      )}
    </Drawer>
  );
}
