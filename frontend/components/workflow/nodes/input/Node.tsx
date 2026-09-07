"use client";

/**
 * M30c 2.0 (2026-09-07): input Node.tsx.
 *
 * Extracted from designer/page.tsx:60-67 (was inline InputNode const).
 * Pure visual component — behavior lives in the backend's
 * ``lumen_core.workflow.nodes.input.InputNode`` class.
 */
import { Card } from "antd";
import { Handle, Position } from "@xyflow/react";

export function InputNode({ data }: { data: any }) {
  return (
    <Card size="small" style={{ minWidth: 150, background: "#f0f0f0" }}>
      <Handle type="target" position={Position.Top} />
      <div style={{ fontWeight: "bold" }}>📥 Input</div>
      <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
      <Handle type="source" position={Position.Bottom} />
    </Card>
  );
}
