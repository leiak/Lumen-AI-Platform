"use client";

/**
 * M30c 2.0 (2026-09-07): fan_in Node.tsx.
 * Extracted from designer/page.tsx:150-159 (was inline FanInNode const).
 */
import { Card } from "antd";
import { Handle, Position } from "@xyflow/react";

export function FanInNode({ data }: { data: any }) {
  return (
    <Card size="small" style={{ minWidth: 150, background: "#fffbe6" }}>
      <Handle type="target" position={Position.Top} />
      <Handle type="target" position={Position.Left} />
      <div style={{ fontWeight: "bold" }}>🔻 Fan-In</div>
      <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
      <Handle type="source" position={Position.Bottom} />
    </Card>
  );
}
