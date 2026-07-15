"use client";

import { Drawer, Tag, Space, Empty, Spin, Descriptions, Alert } from "antd";
import { useEffect, useState } from "react";
import { workflowTemplateApi, WorkflowTemplateDetail } from "@/services/workflowTemplate";
import { useAppMessage, extractErrorDetail } from "../hooks/useAppMessage";

interface Props {
  templateId: number | null;
  onClose: () => void;
}

const NODE_TYPE_COLORS: Record<string, string> = {
  input: "blue",
  output: "green",
  llm: "purple",
  agent: "cyan",
  condition: "orange",
  code: "magenta",
  http: "geekblue",
  tool: "volcano",
  knowledge_retrieval: "gold",
  template_transform: "lime",
  parameter_extractor: "red",
  question_classifier: "pink",
  variable_assigner: "purple",
  variable_aggregator: "cyan",
  parallel: "geekblue",
  fan_out: "orange",
  fan_in: "green",
};

/**
 * M30b: template preview drawer. Shows metadata + the workflow JSON
 * (nodes + edges) in a compact form. We intentionally do NOT paint a
 * full canvas here — preview should be fast, not laggy.
 */
export function TemplatePreview({ templateId, onClose }: Props) {
  const { message } = useAppMessage();
  const [detail, setDetail] = useState<WorkflowTemplateDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (templateId === null) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const res = await workflowTemplateApi.detail(templateId);
        if (!cancelled && res.data.code === 200) {
          setDetail(res.data.data || null);
        }
      } catch (err) {
        if (!cancelled) {
          message.error(extractErrorDetail(err, "加载模板详情失败"));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [templateId, message]);

  return (
    <Drawer
      title={detail ? `模板预览 — ${detail.name}` : "模板预览"}
      open={templateId !== null}
      onClose={onClose}
      width={560}
    >
      {loading && <Spin />}
      {!loading && !detail && <Empty description="未找到模板" />}
      {!loading && detail && (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="名称">{detail.name}</Descriptions.Item>
            <Descriptions.Item label="分类">
              <Tag color="blue">{detail.category}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="标签">
              <Space wrap size={4}>
                {(detail.tags || []).map((t) => (
                  <Tag key={t}>{t}</Tag>
                ))}
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="作者">
              {detail.author_name || `用户 #${detail.author_id}`}
            </Descriptions.Item>
            <Descriptions.Item label="使用次数">{detail.downloads}</Descriptions.Item>
            <Descriptions.Item label="描述">
              {detail.description || "（无描述）"}
            </Descriptions.Item>
          </Descriptions>

          <div>
            <div style={{ fontWeight: 500, marginBottom: 8 }}>节点 ({detail.workflow_json.nodes.length})</div>
            <Space direction="vertical" style={{ width: "100%" }} size={4}>
              {detail.workflow_json.nodes.map((n) => (
                <div
                  key={n.id}
                  style={{
                    border: "1px solid #f0f0f0",
                    borderRadius: 4,
                    padding: "4px 8px",
                    background: "#fafafa",
                    fontSize: 12,
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                  }}
                >
                  <Tag color={NODE_TYPE_COLORS[n.type] || "default"} style={{ margin: 0 }}>
                    {n.type}
                  </Tag>
                  <code style={{ flex: 1, color: "#555" }}>{n.id}</code>
                </div>
              ))}
            </Space>
          </div>

          <div>
            <div style={{ fontWeight: 500, marginBottom: 8 }}>连线 ({detail.workflow_json.edges.length})</div>
            {detail.workflow_json.edges.length === 0 ? (
              <Alert type="info" message="无连线（仅单个节点）" showIcon />
            ) : (
              <Space direction="vertical" style={{ width: "100%" }} size={2}>
                {detail.workflow_json.edges.map((e) => (
                  <div key={e.id} style={{ fontSize: 12, color: "#666" }}>
                    <code>{e.source}</code>
                    {" → "}
                    <code>{e.target}</code>
                    {e.sourceHandle ? ` (${e.sourceHandle})` : ""}
                  </div>
                ))}
              </Space>
            )}
          </div>
        </Space>
      )}
    </Drawer>
  );
}
