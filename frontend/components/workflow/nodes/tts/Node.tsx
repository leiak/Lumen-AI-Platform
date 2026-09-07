"use client";

/**
 * M30c 2.0 (2026-09-07): tts Node.tsx.
 * M35: text-to-speech node (语音合成).
 * Backend runtime class: lumen_core.workflow.nodes.tts.TTSNode.
 */
import { Card, Tag } from "antd";
import { Handle, Position } from "@xyflow/react";

export function TTSNode({ data }: { data: any }) {
  const voice = data?.voice || "default";
  return (
    <Card size="small" style={{ minWidth: 170, background: "#fff7e6" }}>
      <Handle type="target" position={Position.Top} />
      <div style={{ fontWeight: "bold" }}>🔊 语音合成</div>
      <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
      <div style={{ fontSize: 11, marginTop: 4 }}>
        <Tag color="volcano">voice: {voice}</Tag>
      </div>
      <Handle type="source" position={Position.Bottom} />
    </Card>
  );
}
