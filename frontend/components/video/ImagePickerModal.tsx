"use client";

// frontend/components/video/ImagePickerModal.tsx
// M36.1 — pick images from the existing image-generation library to feed
// VideoCompose.source_images.
//
// Opens a modal with a paginated grid of GeneratedImage thumbnails. Caller
// supplies a Set<number> of already-selected ids; we render a checkbox in
// each card. onConfirm returns the freshly merged selection (Set of ids).
// The ComposeModal will then translate those ids into URLs of shape
// `/api/v1/image-generation/{id}/image` and put them in Form.List.

import { useEffect, useState } from "react";
import { Modal, Pagination, Spin, Checkbox, Tag, Empty } from "antd";
import { useQuery } from "@tanstack/react-query";
import { imageGenerationApi } from "@/services/image-generation";
import type { ImageGenerationListItem } from "@/types/image-generation";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:11335/api/v1";

const PAGE_SIZE = 24;

export interface ImagePickerModalProps {
  open: boolean;
  initialSelected: number[];
  onClose: () => void;
  onConfirm: (ids: number[]) => void;
}

export function ImagePickerModal({
  open,
  initialSelected,
  onClose,
  onConfirm,
}: ImagePickerModalProps) {
  const [page, setPage] = useState(1);
  // Set 是为了 O(1) toggle,但 onConfirm 时回到 array 给父。
  const [selected, setSelected] = useState<Set<number>>(new Set(initialSelected));

  // 每次打开都重置选择 + 页码 —— 避免 stale state 污染下一次。
  useEffect(() => {
    if (open) {
      setSelected(new Set(initialSelected));
      setPage(1);
    }
  }, [open, initialSelected]);

  // 用同一个 imageGenerationApi.list() 拉当前 tenant 的图片。
  const { data, isLoading } = useQuery({
    queryKey: ["image-generation", "video-picker", page],
    queryFn: () =>
      imageGenerationApi.list({
        page,
        page_size: PAGE_SIZE,
        status: "completed",
      }),
    enabled: open,
  });

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const items = data?.items ?? [];

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title="从我的图片库选"
      width={840}
      destroyOnHidden
      okText={`确定 (${selected.size})`}
      cancelText="取消"
      onOk={() => onConfirm(Array.from(selected))}
      okButtonProps={{ disabled: selected.size === 0 }}
    >
      {isLoading ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : items.length === 0 ? (
        <Empty description="还没有生成的图片,先去图片生成页生成几张" />
      ) : (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
              gap: 12,
            }}
          >
            {items.map((item: ImageGenerationListItem) => {
              const checked = selected.has(item.id);
              return (
                <div
                  key={item.id}
                  onClick={() => toggle(item.id)}
                  style={{
                    position: "relative",
                    cursor: "pointer",
                    border: checked ? "2px solid #1677ff" : "2px solid transparent",
                    borderRadius: 6,
                    overflow: "hidden",
                    background: "#f5f5f5",
                  }}
                >
                  <img
                    src={`${API_BASE}${imageGenerationApi.thumbnailPath(item.id)}`}
                    alt={item.prompt_preview}
                    style={{
                      width: "100%",
                      height: 140,
                      objectFit: "cover",
                      display: "block",
                    }}
                  />
                  <div
                    style={{
                      position: "absolute",
                      top: 4,
                      right: 4,
                      background: "rgba(255,255,255,0.9)",
                      borderRadius: 4,
                      padding: 2,
                    }}
                  >
                    <Checkbox checked={checked} onChange={() => toggle(item.id)} />
                  </div>
                  <div
                    style={{
                      padding: 4,
                      fontSize: 12,
                      background: "rgba(0,0,0,0.5)",
                      color: "#fff",
                      position: "absolute",
                      bottom: 0,
                      left: 0,
                      right: 0,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                    title={item.prompt_preview}
                  >
                    {item.prompt_preview || `image-${item.id}`}
                    <Tag style={{ marginLeft: 4 }}>{item.size}</Tag>
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