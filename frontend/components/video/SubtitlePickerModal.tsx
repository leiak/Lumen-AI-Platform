"use client";

// frontend/components/video/SubtitlePickerModal.tsx
// M36.1.1 — pick a subtitle from the user's library to feed
// VideoCompose.subtitle_path. Backend resolves the returned id string
// to the on-disk SRT/VTT file via `_resolve_asset_to_path` in
// `backend/lumen_services/video_compose_service.py:25`.
//
// SubtitleListItem has no status field — completed subtitle rows
// are the only kind the API returns. We show language, cue_count,
// duration_ms, char_count, and the tts_job_id link if present.

import { useEffect, useState } from "react";
import { Modal, Pagination, Spin, Empty, Tag, Typography } from "antd";
import { useQuery } from "@tanstack/react-query";
import { listSubtitles } from "@/services/subtitle";
import type { SubtitleListItem } from "@/types/subtitle";

const { Text } = Typography;

const PAGE_SIZE = 20;

export interface SubtitlePickerModalProps {
  open: boolean;
  onClose: () => void;
  /** Receives the chosen subtitle id (backend resolves it to a path). */
  onConfirm: (subtitleId: number) => void;
}

export function SubtitlePickerModal({
  open,
  onClose,
  onConfirm,
}: SubtitlePickerModalProps) {
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    if (open) {
      setSelected(null);
      setPage(1);
    }
  }, [open]);

  const { data, isLoading } = useQuery({
    queryKey: ["subtitles", "subtitle-picker", page],
    queryFn: () => listSubtitles({ page, page_size: PAGE_SIZE }),
    enabled: open,
  });

  const items = data?.items ?? [];

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title="从我的字幕库选"
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
        <Empty description="还没有字幕,先去 TTS 页生成一段会附带字幕" />
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
            {items.map((sub: SubtitleListItem) => {
              const isSelected = selected === sub.id;
              const dur = sub.duration_ms
                ? `${(sub.duration_ms / 1000).toFixed(1)}s`
                : "—";
              return (
                <div
                  key={sub.id}
                  onClick={() => setSelected(isSelected ? null : sub.id)}
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
                      <Text strong>#{sub.id}</Text>
                      <Tag color="purple">{sub.language}</Tag>
                      <Tag color="blue">{sub.cue_count} cues</Tag>
                      <Tag color="green">{dur}</Tag>
                      <Tag>{sub.char_count} 字</Tag>
                      {sub.tts_job_id !== null && (
                        <Tag color="orange">tts #{sub.tts_job_id}</Tag>
                      )}
                    </div>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {new Date(sub.created_at).toLocaleString()}
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