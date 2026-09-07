"use client";

/**
 * M30c 2.0 (2026-09-07): condition Node.tsx.
 * Extracted from designer/page.tsx:112-120 (was inline ConditionNode const).
 */
import { Card } from "antd";
import { Handle, Position } from "@xyflow/react";

export function ConditionNode({ data }: { data: any }) {
  return (
    <Card size="small" style={{ minWidth: 150, background: "#fff7e6" }}>
      <Handle type="target" position={Position.Top} />
      <div style={{ fontWeight: "bold" }}>🔀 Condition</div>
      <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
      <Handle type="source" position={Position.Bottom} style={{ left: "30%" }} />
      <Handle type="source" position={Position.Bottom} style={{ left: "70%" }} />
    </Card>
  );
}
