"use client";

// frontend/components/video/VideoCard.tsx
// M36.1 — list-page row card.
//
// Unlike ImageCard we don't render an inline thumbnail (no video thumbnail
// endpoint exists in the backend — only the full mp4 download). Instead the
// card shows a status badge + key meta (resolution, fps, image count, size)
// and the page wraps the card in row-level 操作 (取消/下载/删除). Hovering
// the card highlights it; clicking opens DetailModal.

import { Tag, Typography, Space } from "antd";
import {
  LoadingOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  StopOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import "dayjs/locale/zh-cn";
import type { VideoListItem, VideoStatus } from "@/types/video";

dayjs.extend(relativeTime);
dayjs.locale("zh-cn");

const { Text } = Typography;

const STATUS_META: Record<
  VideoStatus,
  { color: string; label: string; icon: React.ReactNode }
> = {
  pending: { color: "default", label: "排队中", icon: <LoadingOutlined /> },
  composing: { color: "processing", label: "合成中", icon: <LoadingOutlined /> },
  completed: { color: "success", label: "已完成", icon: <CheckCircleOutlined /> },
  failed: { color: "error", label: "失败", icon: <CloseCircleOutlined /> },
  cancelled: { color: "warning", label: "已取消", icon: <StopOutlined /> },
};

export interface VideoCardProps {
  item: VideoListItem;
  onClick: () => void;
}

export function VideoCard({ item, onClick }: VideoCardProps) {
  const status = STATUS_META[item.status] ?? STATUS_META.pending;
  const durationSec =
    item.duration_ms != null ? (item.duration_ms / 1000).toFixed(1) : "—";

  return (
    <div
      onClick={onClick}
      style={{
        cursor: "pointer",
        padding: 16,
        borderRadius: 8,
        background: "#fafafa",
        textAlign: "center",
        minHeight: 120,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
      }}
    >
      <div style={{ fontSize: 36, color: status.color === "success" ? "#52c41a" : "#999" }}>
        {status.icon}
      </div>
      <Tag color={status.color}>{status.label}</Tag>
      <Text strong style={{ fontSize: 13 }}>
        Video #{item.id}
      </Text>
      <Space size={4} wrap>
        <Tag>{item.resolution}</Tag>
        <Tag>{item.fps} fps</Tag>
        <Tag>{durationSec}s</Tag>
      </Space>
      <Text type="secondary" style={{ fontSize: 12 }}>
        {dayjs(item.created_at).fromNow()}
      </Text>
    </div>
  );
}