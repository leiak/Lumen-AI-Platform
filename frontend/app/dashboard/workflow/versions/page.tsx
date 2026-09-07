"use client";

import { useEffect, useState } from "react";
import { Card, Table, Tag, Select, Space, Button } from "antd";
import {
  BranchesOutlined,
  ReloadOutlined,
  ArrowLeftOutlined,
  EyeOutlined,
} from "@ant-design/icons";
import { useRouter, useSearchParams } from "next/navigation";
import type { ColumnsType } from "antd/es/table";
import { workflowApi, Workflow, WorkflowVersion } from "@/services/workflow";
import { useAppMessage, extractErrorDetail } from "../hooks/useAppMessage";

/**
 * M30b 2.0 (2026-09-07): /dashboard/workflow/versions — 版本快照列表。
 *
 * 2.0 阶段版本表是 read-only,UI 只能看 + 跳详情(2.1 接写)。
 * 顶部 workflow 选择器(必填),跟 /runs 子页同款 pattern。
 *
 * Query 参数:
 *   - workflow_id: 预选 workflow(从列表行 "版本" 按钮跳过来)
 */
export default function WorkflowVersionsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialWorkflowId = searchParams.get("workflow_id");

  const { message } = useAppMessage();
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [workflowId, setWorkflowId] = useState<number | null>(
    initialWorkflowId ? Number(initialWorkflowId) : null,
  );
  const [versions, setVersions] = useState<WorkflowVersion[]>([]);
  const [loading, setLoading] = useState(false);

  // workflow 下拉
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

  // 版本列表
  useEffect(() => {
    if (workflowId === null) {
      setVersions([]);
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const resp = await workflowApi.listVersions(workflowId);
        if (cancelled) return;
        if (resp.data.code === 200) {
          setVersions(resp.data.data || []);
        }
      } catch (error) {
        if (!cancelled) {
          message.error(extractErrorDetail(error, "加载版本快照失败"));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workflowId, message]);

  const columns: ColumnsType<WorkflowVersion> = [
    {
      title: "版本号",
      dataIndex: "version",
      key: "version",
      width: 100,
      render: (v: number) => <Tag color="blue">v{v}</Tag>,
    },
    {
      title: "节点数",
      key: "node_count",
      width: 100,
      render: (_, r) => r.definition_snapshot?.nodes?.length ?? 0,
    },
    {
      title: "变更说明",
      dataIndex: "change_summary",
      key: "change_summary",
      ellipsis: true,
      render: (v: string | null | undefined) => v || <span style={{ color: "#bbb" }}>—</span>,
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 180,
      render: (v: string) => (v ? new Date(v).toLocaleString() : "-"),
    },
    {
      title: "操作",
      key: "action",
      width: 120,
      render: (_, record) => (
        <Button
          size="small"
          icon={<EyeOutlined />}
          onClick={() =>
            router.push(
              `/dashboard/workflow/versions/${record.id}?workflow_id=${record.workflow_id}`,
            )
          }
        >
          查看
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
            <BranchesOutlined />
            <span>版本快照</span>
          </Space>
        }
        extra={
          <Button
            icon={<ReloadOutlined />}
            disabled={workflowId === null}
            onClick={() => {
              setVersions([]);
              // 触发 useEffect
              const cur = workflowId;
              setWorkflowId(null);
              setTimeout(() => setWorkflowId(cur), 0);
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
            onChange={(v) => setWorkflowId(v ?? null)}
            options={workflows.map((w) => ({ label: w.name, value: w.id }))}
            showSearch
            optionFilterProp="label"
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
            dataSource={versions}
            pagination={false}
            locale={{
              emptyText: loading
                ? "加载中…"
                : "该工作流还没有版本快照(2.0 仅读;2.1 写)",
            }}
            columns={columns}
          />
        )}
      </Card>
    </div>
  );
}
