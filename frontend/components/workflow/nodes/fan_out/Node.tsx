"use client";

/**
 * M30c 2.0 (2026-09-07): fan_out Node.tsx.
 * Extracted from designer/page.tsx:140-148 (was inline FanOutNode const).
 */
import { Card } from "antd";
import { Handle, Position } from "@xyflow/react";

export function FanOutNode({ data }: { data: any }) {
  return (
    <Card size="small" style={{ minWidth: 150, background: "#f0f5ff" }}>
      <Handle type="target" position={Position.Top} />
      <div style={{ fontWeight: "bold" }}>🔱 Fan-Out</div>
      <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
      <Handle type="source" position={Position.Bottom} />
    </Card>
  );
}
