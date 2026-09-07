"use client";

import { useEffect, useState } from "react";
import { Table, Tag, Button, Select, Space, Card } from "antd";
import {
  HistoryOutlined,
  ReloadOutlined,
  ArrowLeftOutlined,
} from "@ant-design/icons";
import { useRouter, useSearchParams } from "next/navigation";
import type { ColumnsType } from "antd/es/table";
import { workflowApi, Workflow, WorkflowRun } from "@/services/workflow";
import { useAppMessage, extractErrorDetail } from "../hooks/useAppMessage";

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
 * M30b 2.0 (2026-09-07): /dashboard/workflow/runs — 全工作流运行历史。
 *
 * 之前是 page.tsx 里的 RunHistoryDrawer;M30b 拆成独立子页,带
 * workflow_id select(可指定 / 显示全部)+ status 过滤 + 分页。
 *
 * Query 参数:
 *   - workflow_id: 预选 workflow(从列表行 "历史" 按钮跳过来)
 */
export default function WorkflowRunsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialWorkflowId = searchParams.get("workflow_id");

  const { message } = useAppMessage();
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [workflowId, setWorkflowId] = useState<number | null>(
    initialWorkflowId ? Number(initialWorkflowId) : null,
  );
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [total, setTotal] = useState(0);

  // 加载 workflow 下拉选项(限 100 条,够用)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await workflowApi.list(1, 100);
        if (cancelled) return;
        if (resp.data.code === 200) {
          setWorkflows(resp.data.data || []);
        }
      } catch (error) {
        if (!cancelled) {
          message.error(extractErrorDetail(error, "加载工作流列表失败"));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [message]);

  // 加载 runs
  useEffect(() => {
    if (workflowId === null) {
      setRuns([]);
      setTotal(0);
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const resp = await workflowApi.listRuns(workflowId, page, pageSize);
        if (cancelled) return;
        if (resp.data.code === 200) {
          let items: WorkflowRun[] = resp.data.data || [];
          if (statusFilter) {
            items = items.filter((r) => r.status === statusFilter);
          }
          setRuns(items);
          setTotal(resp.data.total || 0);
        }
      } catch (error) {
        if (!cancelled) {
          message.error(extractErrorDetail(error, "加载运行历史失败"));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workflowId, page, pageSize, statusFilter, message]);

  const columns: ColumnsType<WorkflowRun> = [
    { title: "ID", dataIndex: "id", key: "id", width: 80 },
    {
      title: "触发",
      dataIndex: "trigger_source",
      key: "trigger_source",
      width: 100,
      render: (v: string | null | undefined) =>
        v === "scheduled" ? (
          <Tag color="blue">定时</Tag>
        ) : v === "resume" ? (
          <Tag color="orange">续跑</Tag>
        ) : v === "continue" ? (
          <Tag color="purple">续跑(跳已成功)</Tag>
        ) : (
          <Tag>手动</Tag>
        ),
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 100,
      render: (v: string) => <Tag color={statusColor(v)}>{v}</Tag>,
    },
    {
      title: "开始",
      dataIndex: "started_at",
      key: "started_at",
      width: 180,
      render: (v: string | null | undefined) =>
        v ? new Date(v).toLocaleString() : "-",
    },
    {
      title: "耗时",
      key: "duration",
      width: 100,
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
    {
      title: "操作",
      key: "action",
      width: 120,
      render: (_, record) => (
        <Button
          size="small"
          icon={<HistoryOutlined />}
          onClick={() => router.push(`/dashboard/workflow/runs/${record.id}`)}
        >
          详情
        </Button>
      ),
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
              onClick={() => router.push("/dashboard/workflow")}
            >
              返回列表
            </Button>
            <HistoryOutlined />
            <span>运行历史</span>
          </Space>
        }
        extra={
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              setPage(1);
              // 触发 useEffect 重新加载
              setWorkflowId((prev) => (prev === null ? -1 : prev));
              setTimeout(() => setWorkflowId((prev) => (prev === -1 ? null : prev)), 0);
            }}
          >
            刷新
          </Button>
        }
      >
        <Space style={{ marginBottom: 16 }} wrap>
          <span>工作流:</span>
          <Select
            allowClear
            placeholder="选择工作流(必填)"
            style={{ minWidth: 240 }}
            value={workflowId ?? undefined}
            onChange={(v) => {
              setWorkflowId(v ?? null);
              setPage(1);
            }}
            options={workflows.map((w) => ({ label: w.name, value: w.id }))}
            showSearch
            optionFilterProp="label"
          />
          <span>状态:</span>
          <Select
            allowClear
            placeholder="全部"
            style={{ minWidth: 140 }}
            value={statusFilter ?? undefined}
            onChange={(v) => {
              setStatusFilter(v ?? null);
              setPage(1);
            }}
            options={[
              { label: "completed", value: "completed" },
              { label: "failed", value: "failed" },
              { label: "running", value: "running" },
              { label: "cancelled", value: "cancelled" },
            ]}
          />
        </Space>
        {workflowId === null ? (
          <div style={{ color: "#999", padding: 32, textAlign: "center" }}>
            请先选择工作流。
          </div>
        ) : (
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
              onChange: (p, ps) => {
                setPage(p);
                setPageSize(ps);
              },
            }}
            columns={columns}
          />
        )}
      </Card>
    </div>
  );
}
