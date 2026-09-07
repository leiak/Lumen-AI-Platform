"use client";

/**
 * M30c 2.0 (2026-09-07): output Node.tsx.
 * Extracted from designer/page.tsx:122-128 (was inline OutputNode const).
 */
import { Card } from "antd";
import { Handle, Position } from "@xyflow/react";

export function OutputNode({ data }: { data: any }) {
  return (
    <Card size="small" style={{ minWidth: 150, background: "#f6ffed" }}>
      <Handle type="target" position={Position.Top} />
      <div style={{ fontWeight: "bold" }}>📤 Output</div>
      <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
    </Card>
  );
}
