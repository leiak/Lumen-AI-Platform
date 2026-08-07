"use client";

// frontend/components/video/MusicPickerModal.tsx
// M36.2.2 — pick a background-music track from the global builtin +
// per-tenant library to feed VideoCompose.background_music_path.
//
// Mirrors `AudioPickerModal` (single-select list picker), with the
// addition of an inline `<audio controls>` preview that uses the
// fetch + Bearer + blob + createObjectURL pattern (MEMORY 2026-06-20)
// so `<audio src=...>` doesn't have to send auth headers itself.
//
// Single-select: tap a row → row highlights + auto-fetches the audio
// blob for preview. Tap OK → commit the chosen id via `onConfirm`.

import { useEffect, useState } from "react";
import { Modal, Pagination, Spin, Empty, Tag, Typography } from "antd";
import { useQuery } from "@tanstack/react-query";
import { listStockMusics, buildStockMusicUrl } from "@/services/stock-music";
import type { StockMusicListItem } from "@/types/stock-music";

const { Text } = Typography;

const PAGE_SIZE = 24;

const CATEGORY_OPTIONS = [
  { value: "舒缓", label: "舒缓" },
  { value: "振奋", label: "振奋" },
  { value: "戏剧", label: "戏剧" },
  { value: "商务", label: "商务" },
  { value: "氛围", label: "氛围" },
];

export interface MusicPickerModalProps {
  open: boolean;
  initialSelected: number | null;
  onClose: () => void;
  /** Receives the chosen BGM id as a number; backend resolves it. */
  onConfirm: (musicId: number) => void;
}

function formatDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return "—";
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// 预览音频子组件。``<audio src=...>`` 不能设 Authorization 头(MEMORY
// 2026-06-20),所以走 fetch + Bearer + blob + createObjectURL 模式。
function MusicAudioPreview({ id, name }: { id: number; name: string }) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [errored, setErrored] = useState(false);
  useEffect(() => {
    let cancelled = false;
    const token =
      typeof window !== "undefined"
        ? localStorage.getItem("access_token")
        : null;
    fetch(buildStockMusicUrl(id), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => {
        if (!r.ok) throw new Error(`music fetch failed: ${r.status}`);
        return r.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        setBlobUrl(URL.createObjectURL(blob));
      })
      .catch(() => {
        if (cancelled) return;
        setErrored(true);
      });
    return () => {
      cancelled = true;
      setBlobUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return null;
      });
    };
  }, [id]);
  if (errored) {
    return (
      <Text type="secondary" style={{ fontSize: 12 }}>
        音频加载失败
      </Text>
    );
  }
  if (!blobUrl) {
    return (
      <Text type="secondary" style={{ fontSize: 12 }}>
        加载中…
      </Text>
    );
  }
  return (
    // controls + no autoplay: user controls playback explicitly. 防止后
    // 台一次性下载多个 mp3 浪费带宽,只选中的行才挂 <audio>。
    <audio
      controls
      src={blobUrl}
      preload="none"
      style={{ width: "100%" }}
      aria-label={`preview-${name}`}
    />
  );
}

export function MusicPickerModal({
  open,
  initialSelected,
  onClose,
  onConfirm,
}: MusicPickerModalProps) {
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<number | null>(initialSelected);
  const [category, setCategory] = useState<string | undefined>();

  // 每次打开 modal 重置 pagination + selection,避免 stale state 污染。
  useEffect(() => {
    if (open) {
      setSelected(initialSelected);
      setPage(1);
      setCategory(undefined);
    }
  }, [open, initialSelected]);

  const { data, isLoading } = useQuery({
    queryKey: ["stock-musics", "music-picker", page, category],
    queryFn: () =>
      listStockMusics({
        page,
        page_size: PAGE_SIZE,
        category,
      }),
    enabled: open,
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title="从背景音乐库选"
      width={720}
      destroyOnHidden
      okText="确定"
      cancelText="取消"
      onOk={() => selected !== null && onConfirm(selected)}
      okButtonProps={{ disabled: selected === null }}
    >
      <div
        style={{
          display: "flex",
          gap: 8,
          marginBottom: 12,
          alignItems: "center",
        }}
      >
        <select
          value={category ?? ""}
          onChange={(e) => {
            setCategory(e.target.value || undefined);
            setPage(1);
          }}
          style={{
            padding: "4px 8px",
            borderRadius: 4,
            border: "1px solid #d9d9d9",
            fontSize: 14,
            background: "#fff",
          }}
        >
          <option value="">全部分类</option>
          {CATEGORY_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <span style={{ color: "#888", fontSize: 12, marginLeft: "auto" }}>
          共 {total} 首
        </span>
      </div>
      {isLoading ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : items.length === 0 ? (
        <Empty description="没有匹配的音乐 — 先到 system 页面 seed" />
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
            {items.map((m: StockMusicListItem) => {
              const isSelected = selected === m.id;
              return (
                <div
                  key={m.id}
                  onClick={() => setSelected(isSelected ? null : m.id)}
                  style={{
                    padding: 12,
                    border: isSelected
                      ? "2px solid #1677ff"
                      : "1px solid #f0f0f0",
                    borderRadius: 6,
                    cursor: "pointer",
                    background: isSelected ? "#e6f4ff" : "#fafafa",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      marginBottom: isSelected ? 8 : 0,
                    }}
                  >
                    <Text strong>#{m.id}</Text>
                    <Text strong style={{ flex: 1, minWidth: 0 }} ellipsis={{ tooltip: m.name }}>
                      {m.name}
                    </Text>
                    <Tag color="blue">{m.category}</Tag>
                    <Tag>{formatDuration(m.duration_seconds)}</Tag>
                    <Tag>{(m.file_size / 1024).toFixed(0)} KB</Tag>
                  </div>
                  {isSelected && (
                    <MusicAudioPreview id={m.id} name={m.name} />
                  )}
                  {m.description && (
                    <Text
                      type="secondary"
                      style={{ fontSize: 12, marginTop: 4, display: "block" }}
                      ellipsis={{ tooltip: m.description }}
                    >
                      {m.description}
                    </Text>
                  )}
                </div>
              );
            })}
          </div>
          <div style={{ marginTop: 16, textAlign: "right" }}>
            <Pagination
              current={page}
              pageSize={PAGE_SIZE}
              total={total}
              showSizeChanger={false}
              onChange={setPage}
            />
          </div>
        </>
      )}
    </Modal>
  );
}
