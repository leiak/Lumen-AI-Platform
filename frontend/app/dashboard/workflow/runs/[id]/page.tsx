"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Card, Tag, Alert, Space, Table, Button, Spin } from "antd";
import {
  ArrowLeftOutlined,
  ReloadOutlined,
  HistoryOutlined,
  RetweetOutlined,
  StepForwardOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { workflowApi, WorkflowRun, WorkflowNodeRun } from "@/services/workflow";
import api from "@/services/auth";
import type { ApiResponse } from "@/types/api";
import { useAppMessage, extractErrorDetail } from "../../hooks/useAppMessage";

const statusColor = (status: string) =>
  status === "completed"
    ? "green"
    : status === "failed"
      ? "red"
      : status === "running"
        ? "blue"
        : status === "cancelled"
          ? "default"
          : "default";

const fmtDuration = (
  started: string | null | undefined,
  finished: string | null | undefined,
) => {
  if (!started || !finished) return "-";
  const ms = new Date(finished).getTime() - new Date(started).getTime();
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`;
  return `${(ms / 60_000).toFixed(2)} min`;
};

/**
 * M30b 2.0 (2026-09-07): /dashboard/workflow/runs/[id] — 单次 run 详情。
 *
 * 之前是 page.tsx 里的 RunDetailDrawer;M30b 拆成独立子页,URL 只带
 * run_id,通过新增的 GET /workflows/runs/{run_id} 取 run metadata。
 * 节点执行明细走原有 GET /workflows/{wf_id}/runs/{run_id}/nodes。
 *
 * 行动按钮:
 *   - 重试(同输入) = POST /resume(M30d,沿用)
 *   - 续跑(跳已成功)= POST /continue(M30d 2.0,新)
 */
export default function WorkflowRunDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const runId = Number(params.id);
  const { message } = useAppMessage();

  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [nodeRuns, setNodeRuns] = useState<WorkflowNodeRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [resuming, setResuming] = useState(false);
  const [continuing, setContinuing] = useState(false);

  const fetchAll = async () => {
    if (!Number.isFinite(runId)) return;
    setLoading(true);
    try {
      const runResp = await workflowApi.getRun(runId);
      if (runResp.data.code !== 200 || !runResp.data.data) {
        message.error("未找到该 Run");
        setRun(null);
        return;
      }
      const r = runResp.data.data;
      setRun(r);
      const nodesResp = await workflowApi.listRunNodes(r.workflow_id, runId);
      if (nodesResp.data.code === 200) {
        setNodeRuns(nodesResp.data.data || []);
      }
    } catch (error) {
      message.error(extractErrorDetail(error, "加载 Run 详情失败"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const handleResume = async () => {
    if (!run) return;
    setResuming(true);
    try {
      const resp = await api.post<ApiResponse<WorkflowRun>>(
        `/workflows/${run.workflow_id}/runs/${runId}/resume`,
      );
      if (resp.data.code === 200 && resp.data.data) {
        message.success("已重试,新 Run #" + resp.data.data.id);
        router.push(`/dashboard/workflow/runs/${resp.data.data.id}`);
      } else {
        message.error(resp.data.message || "重试失败");
      }
    } catch (error) {
      message.error(extractErrorDetail(error, "重试失败"));
    } finally {
      setResuming(false);
    }
  };

  const handleContinue = async () => {
    if (!run) return;
    setContinuing(true);
    try {
      const resp = await api.post<ApiResponse<WorkflowRun>>(
        `/workflows/${run.workflow_id}/runs/${runId}/continue`,
      );
      if (resp.data.code === 200 && resp.data.data) {
        message.success("已续跑,新 Run #" + resp.data.data.id);
        router.push(`/dashboard/workflow/runs/${resp.data.data.id}`);
      } else {
        message.error(resp.data.message || "续跑失败");
      }
    } catch (error) {
      message.error(extractErrorDetail(error, "续跑失败"));
    } finally {
      setContinuing(false);
    }
  };

  if (loading && !run) {
    return (
      <div style={{ padding: 24, textAlign: "center" }}>
        <Spin tip="加载中…" />
      </div>
    );
  }

  if (!run) {
    return (
      <div style={{ padding: 24 }}>
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() => router.push("/dashboard/workflow/runs")}
        >
          返回运行历史
        </Button>
        <div style={{ marginTop: 16, color: "#999" }}>未找到 Run #{runId}</div>
      </div>
    );
  }

  const canRetry = run.status === "failed" || run.status === "cancelled";
  const canContinue = run.status === "failed";

  const nodeColumns: ColumnsType<WorkflowNodeRun> = [
    { title: "顺序", dataIndex: "execution_order", key: "order", width: 60 },
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
      width: 100,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 100,
      render: (v: string) => <Tag color={statusColor(v)}>{v}</Tag>,
    },
    {
      title: "耗时",
      key: "duration",
      width: 90,
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
  ];

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={
          <Space>
            <Button
              type="text"
              icon={<ArrowLeftOutlined />}
              onClick={() =>
                router.push(
                  `/dashboard/workflow/runs?workflow_id=${run.workflow_id}`,
                )
              }
            >
              返回历史
            </Button>
            <HistoryOutlined />
            <span>Run #{run.id}</span>
          </Space>
        }
        extra={
          <Space>
            {canRetry && (
              <Button
                icon={<RetweetOutlined />}
                loading={resuming}
                onClick={handleResume}
              >
                重试(同输入)
              </Button>
            )}
            {canContinue && (
              <Button
                type="primary"
                icon={<StepForwardOutlined />}
                loading={continuing}
                onClick={handleContinue}
              >
                续跑(跳已成功)
              </Button>
            )}
            <Button icon={<ReloadOutlined />} onClick={fetchAll}>
              刷新
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Space wrap>
            <span>
              状态: <Tag color={statusColor(run.status)}>{run.status}</Tag>
            </span>
            <span>
              触发:{" "}
              {run.trigger_source === "scheduled" ? (
                <Tag color="blue">定时</Tag>
              ) : run.trigger_source === "resume" ? (
                <Tag color="orange">续跑(同输入)</Tag>
              ) : run.trigger_source === "continue" ? (
                <Tag color="purple">续跑(跳已成功)</Tag>
              ) : (
                <Tag>手动</Tag>
              )}
            </span>
            <span>工作流: {run.workflow_id}</span>
            <span>
              开始:{" "}
              {run.started_at
                ? new Date(run.started_at).toLocaleString()
                : "-"}
            </span>
            <span>
              结束:{" "}
              {run.finished_at
                ? new Date(run.finished_at).toLocaleString()
                : "-"}
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
          {run.input_data && Object.keys(run.input_data).length > 0 && (
            <div>
              <div style={{ fontWeight: 500, marginBottom: 6 }}>输入</div>
              <pre
                style={{
                  whiteSpace: "pre-wrap",
                  background: "#fafafa",
                  padding: 8,
                  borderRadius: 4,
                  fontSize: 12,
                  maxHeight: 180,
                  overflow: "auto",
                }}
              >
                {JSON.stringify(run.input_data, null, 2)}
              </pre>
            </div>
          )}
          {run.output_data && Object.keys(run.output_data).length > 0 && (
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
            <div style={{ fontWeight: 500, marginBottom: 6 }}>节点执行</div>
            <Table
              rowKey="id"
              size="small"
              loading={loading}
              dataSource={nodeRuns}
              pagination={false}
              locale={{ emptyText: loading ? "加载中…" : "无节点记录" }}
              columns={nodeColumns}
            />
          </div>
        </Space>
      </Card>
    </div>
  );
}
