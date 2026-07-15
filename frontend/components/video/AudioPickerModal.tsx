"use client";

// frontend/components/video/AudioPickerModal.tsx
// M36.1.1 — pick a TTS audio from the user's job history to feed
// VideoCompose.audio_path. Backend resolves the returned id string to
// the on-disk file via `_resolve_asset_to_path` in
// `backend/lumen_services/video_compose_service.py:25` (audio_path also
// accepts a local path string — the modal is just the picker; the Input
// in ComposeModal remains the source of truth).
//
// Single-select: tapping a row toggles selection; OK button commits the
// chosen id. We filter to status="completed" by default since pending /
// composing / failed jobs have no on-disk audio yet.

import { useEffect, useState } from "react";
import { Modal, Pagination, Spin, Empty, Tag, Typography } from "antd";
import { useQuery } from "@tanstack/react-query";
import { listTTSJobs } from "@/services/tts";
import type { TTSJobListItem } from "@/types/tts";

const { Text } = Typography;

const PAGE_SIZE = 20;

export interface AudioPickerModalProps {
  open: boolean;
  onClose: () => void;
  /** Receives the chosen audio id as a string (backend resolves it). */
  onConfirm: (ttsId: number) => void;
}

const STATUS_COLOR: Record<string, string> = {
  pending: "default",
  running: "processing",
  completed: "success",
  failed: "error",
  cancelled: "warning",
};

export function AudioPickerModal({ open, onClose, onConfirm }: AudioPickerModalProps) {
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<number | null>(null);

  // 打开即重置 — 避免 stale state 污染下一次。
  useEffect(() => {
    if (open) {
      setSelected(null);
      setPage(1);
    }
  }, [open]);

  // 只拉 completed 的音频 — 其他状态没磁盘文件,提交会被 service 拒。
  const { data, isLoading } = useQuery({
    queryKey: ["tts", "audio-picker", page],
    queryFn: () =>
      listTTSJobs({ page, page_size: PAGE_SIZE, status: "completed" }),
    enabled: open,
  });

  const items = data?.items ?? [];

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title="从我的音频库选"
      width={720}
      destroyOnHidden
      okText="确定"
      cancelText="取消"
      onOk={() => selected !== null && onConfirm(selected)}
      okButtonProps={{ disabled: selected === null }}
    >
      {isLoading ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : items.length === 0 ? (
        <Empty description="还没有已完成的 TTS 音频,先去 TTS 页生成一段" />
      ) : (
        <>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 8,
              maxHeight: 420,
              overflowY: "auto",
            }}
          >
            {items.map((job: TTSJobListItem) => {
              const isSelected = selected === job.id;
              const dur = job.duration_ms
                ? `${(job.duration_ms / 1000).toFixed(1)}s`
                : "—";
              return (
                <div
                  key={job.id}
                  onClick={() => setSelected(isSelected ? null : job.id)}
                  style={{
                    padding: 12,
                    border: isSelected
                      ? "2px solid #1677ff"
                      : "1px solid #f0f0f0",
                    borderRadius: 6,
                    cursor: "pointer",
                    background: isSelected ? "#e6f4ff" : "#fafafa",
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        marginBottom: 4,
                      }}
                    >
                      <Text strong>#{job.id}</Text>
                      <Tag color="blue">{job.voice}</Tag>
                      <Tag>{job.format.toUpperCase()}</Tag>
                      <Tag color="green">{dur}</Tag>
                    </div>
                    <Text
                      type="secondary"
                      style={{ fontSize: 12 }}
                      ellipsis={{ tooltip: job.text_preview }}
                    >
                      {job.text_preview || "(无预览)"}
                    </Text>
                  </div>
                </div>
              );
            })}
          </div>
          <div style={{ marginTop: 16, textAlign: "right" }}>
            <Pagination
              current={page}
              pageSize={PAGE_SIZE}
              total={data?.total ?? 0}
              showSizeChanger={false}
              onChange={setPage}
            />
          </div>
        </>
      )}
    </Modal>
  );
}