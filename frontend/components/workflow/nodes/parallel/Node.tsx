"use client";

/**
 * M30c 2.0 (2026-09-07): parallel Node.tsx.
 * Extracted from designer/page.tsx:130-138 (was inline ParallelNode const).
 */
import { Card } from "antd";
import { Handle, Position } from "@xyflow/react";

export function ParallelNode({ data }: { data: any }) {
  return (
    <Card size="small" style={{ minWidth: 150, background: "#fff0f6" }}>
      <Handle type="target" position={Position.Top} />
      <div style={{ fontWeight: "bold" }}>⚡ Parallel</div>
      <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
      <Handle type="source" position={Position.Bottom} style={{ left: "30%" }} />
      <Handle type="source" position={Position.Bottom} style={{ left: "70%" }} />
    </Card>
  );
}
