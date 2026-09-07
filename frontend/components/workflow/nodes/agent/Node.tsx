"use client";

/**
 * M30c 2.0 (2026-09-07): agent Node.tsx.
 * Extracted from designer/page.tsx:69-76 (was inline AgentNode const).
 */
import { Card } from "antd";
import { Handle, Position } from "@xyflow/react";

export function AgentNode({ data }: { data: any }) {
  return (
    <Card size="small" style={{ minWidth: 150, background: "#e6f7ff" }}>
      <Handle type="target" position={Position.Top} />
      <div style={{ fontWeight: "bold" }}>🤖 Agent</div>
      <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
      <Handle type="source" position={Position.Bottom} />
    </Card>
  );
}
