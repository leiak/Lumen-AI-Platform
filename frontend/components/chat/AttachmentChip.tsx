"use client";

import { Tooltip, Tag } from "antd";
import { PaperClipOutlined, CloseOutlined } from "@ant-design/icons";
import type { AttachmentRef } from "@/types/chat";

interface AttachmentChipProps {
  attachment: AttachmentRef;
  onRemove?: () => void;
  /** When true, render in "history" mode (read-only, no close button). */
  readOnly?: boolean;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * A single attachment chip — either editable (in the input row, with X)
 * or read-only (in the message history bubble, click to tooltip).
 */
export function AttachmentChip({ attachment, onRemove, readOnly }: AttachmentChipProps) {
  const tooltipText = readOnly
    ? `已上传 · 仅本次对话使用(${attachment.mime_type})`
    : `${attachment.mime_type} · ${formatSize(attachment.size)}`;

  return (
    <Tooltip title={tooltipText}>
      <Tag
        icon={<PaperClipOutlined />}
        color={readOnly ? "blue" : "default"}
        style={{ marginRight: 4, padding: "2px 8px" }}
        closable={!readOnly && !!onRemove}
        onClose={onRemove}
        closeIcon={<CloseOutlined />}
      >
        {attachment.name} · {formatSize(attachment.size)}
      </Tag>
    </Tooltip>
  );
}
