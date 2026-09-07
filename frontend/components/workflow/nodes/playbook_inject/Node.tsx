"use client";

/**
 * M30c 2.0 (2026-09-07): playbook_inject Node.tsx.
 * M35: 风格注入 — 把 playbook 的关键词/调色/语速等 token 拼接到输入文本。
 * Backend runtime class: lumen_core.workflow.nodes.playbook_inject.PlaybookInjectNode.
 */
import { Card, Tag } from "antd";
import { Handle, Position } from "@xyflow/react";

export function PlaybookInjectNode({ data }: { data: any }) {
  const target = data?.target || "image_prompt";
  return (
    <Card size="small" style={{ minWidth: 170, background: "#fff0f6" }}>
      <Handle type="target" position={Position.Top} />
      <div style={{ fontWeight: "bold" }}>🎨 风格注入</div>
      <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
      <div style={{ fontSize: 11, marginTop: 4 }}>
        <Tag color="magenta">→ {target}</Tag>
      </div>
      <Handle type="source" position={Position.Bottom} />
    </Card>
  );
}
