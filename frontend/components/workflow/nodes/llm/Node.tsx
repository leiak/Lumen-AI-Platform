"use client";

/**
 * M30c 2.0 (2026-09-07): llm Node.tsx.
 * Extracted from designer/page.tsx:78-110 (was inline LLMNode const).
 * Note: Panel.tsx in the same directory is the property panel, not the
 * canvas node — they coexist.
 */
import { Card, Tag } from "antd";
import { Handle, Position } from "@xyflow/react";

export function LLMNode({ data }: { data: any }) {
  const modelLabel = data?.model_name || "未配置模型";
  const hasPrompt = Boolean(data?.prompt?.trim());
  return (
    <Card
      size="small"
      style={{
        minWidth: 180,
        background: "linear-gradient(135deg, #f9f0ff 0%, #efdbff 100%)",
        borderColor: "#b37feb",
      }}
    >
      <Handle type="target" position={Position.Top} />
      <div style={{ fontWeight: "bold", color: "#531dab" }}>✨ LLM</div>
      <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
      <div style={{ fontSize: 11, marginTop: 4 }}>
        <Tag color="purple" style={{ marginRight: 4 }}>
          {modelLabel}
        </Tag>
        {hasPrompt ? (
          <Tag color="green">prompt</Tag>
        ) : (
          <Tag color="default">未填写 prompt</Tag>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </Card>
  );
}
