"use client";

/**
 * M30c 2.0 (2026-09-07): video_compose Node.tsx.
 * M36: 视频合成 — 图像 + 音频 + 字幕 → mp4 (同步等待).
 * Backend runtime class: lumen_core.workflow.nodes.video_compose.VideoComposeNode.
 */
import { Card, Tag } from "antd";
import { Handle, Position } from "@xyflow/react";

export function VideoComposeNode({ data }: { data: any }) {
  const imageCount = Array.isArray(data?.source_images) ? data.source_images.length : 0;
  return (
    <Card size="small" style={{ minWidth: 180, background: "#f9f0ff" }}>
      <Handle type="target" position={Position.Top} />
      <Handle type="target" position={Position.Left} />
      <div style={{ fontWeight: "bold" }}>🎬 视频合成</div>
      <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
      <div style={{ fontSize: 11, marginTop: 4 }}>
        <Tag color="purple">图 × {imageCount}</Tag>
      </div>
      <Handle type="source" position={Position.Bottom} />
    </Card>
  );
}
