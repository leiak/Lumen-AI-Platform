"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import { Card, Tag, Space, Button, Spin, Alert, Descriptions } from "antd";
import {
  ArrowLeftOutlined,
  ReloadOutlined,
  BranchesOutlined,
} from "@ant-design/icons";
import {
  workflowApi,
  Workflow,
  WorkflowVersion,
} from "@/services/workflow";
import { useAppMessage, extractErrorDetail } from "../../hooks/useAppMessage";

/**
 * M30b 2.0 (2026-09-07): /dashboard/workflow/versions/[id] — 单版本详情。
 *
 * 显示该版本的 metadata + definition_snapshot + (如果可拿到当前
 * definition) 简单 diff 占位(节点数 / 边数变化)。
 *
 * 2.0 阶段没有 "保存即 version +1" 触发,所以 currentDefinition === version
 * 时显示 "这是当前定义"。2.1 接入后这里能展示真正的字段级 diff。
 */
export default function WorkflowVersionDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const workflowId = searchParams.get("workflow_id");
  const versionId = Number(params.id);
  const { message } = useAppMessage();

  const [version, setVersion] = useState<WorkflowVersion | null>(null);
  const [current, setCurrent] = useState<Workflow | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchAll = async () => {
    if (!Number.isFinite(versionId) || !workflowId) {
      message.error("URL 缺少 workflow_id 参数");
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const [vResp, wResp] = await Promise.all([
        workflowApi.getVersion(Number(workflowId), versionId),
        workflowApi.get(Number(workflowId)),
      ]);
      if (vResp.data.code === 200 && vResp.data.data) {
        setVersion(vResp.data.data);
      } else {
        message.error(vResp.data.message || "未找到该版本");
      }
      if (wResp.data.code === 200 && wResp.data.data) {
        setCurrent(wResp.data.data);
      }
    } catch (error) {
      message.error(extractErrorDetail(error, "加载版本详情失败"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versionId, workflowId]);

  if (loading && !version) {
    return (
      <div style={{ padding: 24, textAlign: "center" }}>
        <Spin tip="加载中…" />
      </div>
    );
  }

  if (!version) {
    return (
      <div style={{ padding: 24 }}>
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() =>
            router.push(
              workflowId
                ? `/dashboard/workflow/versions?workflow_id=${workflowId}`
                : "/dashboard/workflow",
            )
          }
        >
          返回版本列表
        </Button>
        <div style={{ marginTop: 16, color: "#999" }}>未找到 Version #{versionId}</div>
      </div>
    );
  }

  // 简单 diff:节点数 / 边数变化
  const snapNodes = version.definition_snapshot?.nodes?.length ?? 0;
  const snapEdges = version.definition_snapshot?.edges?.length ?? 0;
  const curNodes = current?.definition?.nodes?.length ?? 0;
  const curEdges = current?.definition?.edges?.length ?? 0;
  const nodeDelta = curNodes - snapNodes;
  const edgeDelta = curEdges - snapEdges;
  const isCurrent = current && current.definition &&
    JSON.stringify(current.definition) === JSON.stringify(version.definition_snapshot);

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
                  workflowId
                    ? `/dashboard/workflow/versions?workflow_id=${workflowId}`
                    : "/dashboard/workflow",
                )
              }
            >
              返回版本列表
            </Button>
            <BranchesOutlined />
            <span>Version #{version.version}</span>
          </Space>
        }
        extra={
          <Button icon={<ReloadOutlined />} onClick={fetchAll}>
            刷新
          </Button>
        }
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="版本号">
              <Tag color="blue">v{version.version}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="创建时间">
              {version.created_at
                ? new Date(version.created_at).toLocaleString()
                : "-"}
            </Descriptions.Item>
            <Descriptions.Item label="节点数">
              {snapNodes}
            </Descriptions.Item>
            <Descriptions.Item label="边数">{snapEdges}</Descriptions.Item>
            <Descriptions.Item label="变更说明" span={2}>
              {version.change_summary || <span style={{ color: "#bbb" }}>—</span>}
            </Descriptions.Item>
          </Descriptions>

          {isCurrent ? (
            <Alert
              type="info"
              showIcon
              message="这与当前定义完全一致"
              description="2.0 阶段不写版本,2.1 接入「保存即 version +1」后会显示真实 diff。"
            />
          ) : current ? (
            <Alert
              type="warning"
              showIcon
              message="与当前定义存在差异"
              description={
                <Space direction="vertical" size={2}>
                  <span>
                    节点数差异: {nodeDelta > 0 ? `+${nodeDelta}` : nodeDelta} (
                    {snapNodes} → {curNodes})
                  </span>
                  <span>
                    边数差异: {edgeDelta > 0 ? `+${edgeDelta}` : edgeDelta} (
                    {snapEdges} → {curEdges})
                  </span>
                </Space>
              }
            />
          ) : null}

          <div>
            <div style={{ fontWeight: 500, marginBottom: 6 }}>定义快照</div>
            <pre
              style={{
                whiteSpace: "pre-wrap",
                background: "#fafafa",
                padding: 8,
                borderRadius: 4,
                fontSize: 12,
                maxHeight: 480,
                overflow: "auto",
              }}
            >
              {JSON.stringify(version.definition_snapshot, null, 2)}
            </pre>
          </div>
        </Space>
      </Card>
    </div>
  );
}
