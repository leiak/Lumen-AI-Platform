"use client";

// frontend/components/video/DetailModal.tsx
// M36.1 — show a composed video.
//
// IMPORTANT (per MEMORY 2026-06-20 + backend docstring at
// `backend/lumen_api/v1/videos.py:139`): <video src=...> cannot set the
// Authorization header, so we fetch + blob + createObjectURL. cleanup
// revokes the previous blob URL to avoid memory leaks.
//
// Detail modal does NOT poll — it's a "click to inspect" view. The page's
// 5s polling is what flips status pending → completed.

import { useEffect, useState } from "react";
import {
  Modal,
  Descriptions,
  Button,
  Popconfirm,
  Tag,
  Space,
  Alert,
  App,
} from "antd";
import {
  DownloadOutlined,
  DeleteOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { cancelVideo, deleteVideo, buildVideoUrl } from "@/services/video";
import type { VideoDetail, VideoStatus } from "@/types/video";

const STATUS_TAG: Record<VideoStatus, { color: string; label: string }> = {
  pending: { color: "default", label: "排队中" },
  composing: { color: "processing", label: "合成中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
  cancelled: { color: "warning", label: "已取消" },
};

export interface DetailModalProps {
  open: boolean;
  detail: VideoDetail | null;
  onClose: () => void;
}

export function DetailModal({ open, detail, onClose }: DetailModalProps) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [videoUrl, setVideoUrl] = useState<string | null>(null);

  const cancelMut = useMutation({
    mutationFn: (id: number) => cancelVideo(id),
    onSuccess: () => {
      message.success("已请求取消 / Cancel requested");
      qc.invalidateQueries({ queryKey: ["videos"] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteVideo(id),
    onSuccess: () => {
      message.success("已删除 / Deleted");
      qc.invalidateQueries({ queryKey: ["videos"] });
      onClose();
    },
    onError: (e: Error) => message.error(e.message),
  });

  // Fetch mp4 bytes via Bearer-authed fetch, then expose as blob URL.
  // <video src=...> cannot pass Authorization headers natively — see
  // MEMORY 2026-06-20 and backend docstring.
  useEffect(() => {
    if (!open || !detail || detail.status !== "completed") {
      setVideoUrl(null);
      return;
    }
    let cancelled = false;
    const token =
      typeof window !== "undefined"
        ? localStorage.getItem("access_token")
        : null;
    fetch(buildVideoUrl(detail.id), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => {
        if (!r.ok) throw new Error(`video fetch failed: ${r.status}`);
        return r.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        setVideoUrl(URL.createObjectURL(blob));
      })
      .catch(() => {
        if (cancelled) return;
        setVideoUrl(null);
        message.error("视频加载失败 / Video load failed");
      });

    return () => {
      cancelled = true;
      // 严格 cleanup —— 防止 blob URL 泄漏。
      setVideoUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return null;
      });
    };
  }, [open, detail?.id, detail?.status, message]);

  if (!detail) return null;

  const status = STATUS_TAG[detail.status] ?? STATUS_TAG.pending;
  const canCancel = detail.status === "pending" || detail.status === "composing";

  return (
    <Modal
      open={open}
      onCancel={onClose}
      width={900}
      footer={null}
      title={`视频详情 #${detail.id}`}
      destroyOnHidden
    >
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        {/* Left: video player or failure alert */}
        <div
          style={{
            flex: 1,
            minWidth: 320,
            textAlign: "center",
            maxHeight: "70vh",
            overflow: "auto",
            background: "#000",
            borderRadius: 6,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {detail.status === "completed" && videoUrl && (
            <video
              src={videoUrl}
              controls
              style={{
                maxWidth: "100%",
                maxHeight: "70vh",
                width: "100%",
              }}
            />
          )}
          {detail.status === "completed" && !videoUrl && (
            <div style={{ color: "#fff", padding: 40 }}>视频加载中…</div>
          )}
          {(detail.status === "pending" || detail.status === "composing") && (
            <div style={{ color: "#fff", padding: 40 }}>
              {detail.status === "pending" ? "等待开始合成…" : "正在合成…"}
            </div>
          )}
          {detail.status === "failed" && detail.error_message && (
            <div style={{ padding: 16, width: "100%" }}>
              <Alert type="error" message={detail.error_message} showIcon />
            </div>
          )}
          {detail.status === "cancelled" && (
            <div style={{ color: "#faad14", padding: 40 }}>已取消</div>
          )}
        </div>

        {/* Right: metadata */}
        <div style={{ flex: 1, minWidth: 280 }}>
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="状态">
              <Tag color={status.color}>{status.label}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="分辨率">{detail.resolution}</Descriptions.Item>
            <Descriptions.Item label="帧率">{detail.fps} fps</Descriptions.Item>
            <Descriptions.Item label="源图片数">
              {detail.source_images?.length ?? 0}
            </Descriptions.Item>
            <Descriptions.Item label="音频">{detail.source_audio_id ?? "-"}</Descriptions.Item>
            <Descriptions.Item label="字幕">{detail.source_subtitle_id ?? "-"}</Descriptions.Item>
            <Descriptions.Item label="Playbook">{detail.playbook_id ?? "-"}</Descriptions.Item>
            <Descriptions.Item label="文件大小">
              {(detail.file_size / 1024).toFixed(1)} KB
            </Descriptions.Item>
            <Descriptions.Item label="时长">
              {detail.duration_ms ? `${(detail.duration_ms / 1000).toFixed(1)} s` : "-"}
            </Descriptions.Item>
            <Descriptions.Item label="MIME">{detail.mime_type}</Descriptions.Item>
            <Descriptions.Item label="创建时间">{detail.created_at}</Descriptions.Item>
            {detail.source_images && detail.source_images.length > 0 && (
              <Descriptions.Item label="源图片列表">
                <div style={{ maxHeight: 120, overflow: "auto", fontSize: 12 }}>
                  {detail.source_images.map((src, i) => (
                    <div key={i} style={{ marginBottom: 2 }}>
                      {src}
                    </div>
                  ))}
                </div>
              </Descriptions.Item>
            )}
            {detail.error_message && (
              <Descriptions.Item label="错误">
                <span style={{ color: "#cf1322" }}>{detail.error_message}</span>
              </Descriptions.Item>
            )}
          </Descriptions>
        </div>
      </div>

      <div style={{ marginTop: 16, textAlign: "right" }}>
        <Space>
          {canCancel && (
            <Popconfirm
              title="确定取消合成?"
              okText="取消合成"
              cancelText="返回"
              onConfirm={() => cancelMut.mutate(detail.id)}
            >
              <Button
                icon={<StopOutlined />}
                loading={cancelMut.isPending}
              >
                取消合成
              </Button>
            </Popconfirm>
          )}
          {detail.status === "completed" && (
            <Button
              icon={<DownloadOutlined />}
              disabled={!videoUrl}
              onClick={() => {
                if (!videoUrl) return;
                const a = document.createElement("a");
                a.href = videoUrl;
                a.download = `video-${detail.id}.mp4`;
                a.click();
              }}
            >
              下载
            </Button>
          )}
          <Popconfirm
            title="确定删除?"
            okText="删除"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            onConfirm={() => deleteMut.mutate(detail.id)}
          >
            <Button danger icon={<DeleteOutlined />} loading={deleteMut.isPending}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      </div>
    </Modal>
  );
}