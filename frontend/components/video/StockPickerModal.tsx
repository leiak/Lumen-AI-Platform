"use client";

// frontend/components/video/StockPickerModal.tsx
// M36.2.1 — pick stock assets from the global + per-tenant library to
// feed VideoCompose.source_images.
//
// Mirrors `ImagePickerModal` (built-in image library) but reads from
// /api/v1/stock-assets. Multi-select; onConfirm returns the freshly merged
// selection. The ComposeModal translates ids into proxy URLs of shape
// `/api/v1/stock-assets/{id}/image` (see `services/stock.buildStockImageUrl`)
// and appends them to Form.List. The image proxy streams bytes with
// Bearer auth, so the gallery thumbnails use the same fetch+blob pattern
// as `<img src=blob:...>` in MEMORY 2026-06-20.

import { useEffect, useMemo, useState } from "react";
import { Modal, Pagination, Spin, Checkbox, Tag, Empty, Input, Select } from "antd";
import { useQuery } from "@tanstack/react-query";
import { listStockAssets, buildStockImageUrl } from "@/services/stock";
import type { StockAssetListItem } from "@/types/stock";

// 缩略图走 fetch + blob + URL.createObjectURL(MEMORY 2026-06-20 / M22 /
// M32.1 follow-up 立的模式)。``<img src=...>`` 不能设 Authorization 头,
// 后端 stock-assets/{id}/image 用 Bearer auth 会 401。
//
// 每个缩略图独立一个 useEffect,mount 时 fetch → createObjectURL,
// unmount / id 变化时 revokeObjectURL 释放。
function StockThumb({ id, alt }: { id: number; alt: string }) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const token =
      typeof window !== "undefined"
        ? localStorage.getItem("access_token")
        : null;
    fetch(buildStockImageUrl(id), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => {
        if (!r.ok) throw new Error(`stock fetch failed: ${r.status}`);
        return r.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        setBlobUrl(URL.createObjectURL(blob));
      })
      .catch(() => {
        if (cancelled) return;
        setBlobUrl(null);
      });
    return () => {
      cancelled = true;
      setBlobUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return null;
      });
    };
  }, [id]);
  if (!blobUrl) {
    // 占位:加载中或失败。等真有图时显示。
    return (
      <div
        style={{
          width: "100%",
          height: 140,
          background: "#eaeaea",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#999",
          fontSize: 12,
        }}
      >
        加载中…
      </div>
    );
  }
  return (
    <img
      src={blobUrl}
      alt={alt}
      style={{
        width: "100%",
        height: 140,
        objectFit: "cover",
        display: "block",
      }}
    />
  );
}

const PAGE_SIZE = 24;

const CATEGORY_OPTIONS = [
  { value: "风景", label: "风景" },
  { value: "抽象", label: "抽象" },
  { value: "商务", label: "商务" },
  { value: "人物", label: "人物" },
  { value: "产品", label: "产品" },
];

export interface StockPickerModalProps {
  open: boolean;
  initialSelected: number[];
  onClose: () => void;
  onConfirm: (ids: number[]) => void;
}

export function StockPickerModal({
  open,
  initialSelected,
  onClose,
  onConfirm,
}: StockPickerModalProps) {
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<number>>(new Set(initialSelected));
  const [category, setCategory] = useState<string | undefined>();
  const [search, setSearch] = useState("");

  // 每次打开 modal 重置 pagination + selection,避免 stale state 污染。
  useEffect(() => {
    if (open) {
      setSelected(new Set(initialSelected));
      setPage(1);
      setCategory(undefined);
      setSearch("");
    }
  }, [open, initialSelected]);

  const { data, isLoading } = useQuery({
    queryKey: ["stock-assets", "video-picker", page, category, search],
    queryFn: () =>
      listStockAssets({
        page,
        page_size: PAGE_SIZE,
        category,
        search: search || undefined,
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
  const total = data?.total ?? 0;

  const summary = useMemo(
    () => `共 ${total} 张,已选 ${selected.size} 张`,
    [total, selected.size],
  );

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title="从素材库选"
      width={840}
      destroyOnHidden
      okText={`确定 (${selected.size})`}
      cancelText="取消"
      onOk={() => onConfirm(Array.from(selected))}
      okButtonProps={{ disabled: selected.size === 0 }}
    >
      <div
        style={{
          display: "flex",
          gap: 8,
          marginBottom: 12,
          alignItems: "center",
        }}
      >
        <Select
          allowClear
          placeholder="分类"
          virtual={false} // ≤ 5 options → 关 virtual 避免 rc-virtual-list 吞选项
          style={{ width: 140 }}
          options={CATEGORY_OPTIONS}
          value={category}
          onChange={(v) => {
            setCategory(v);
            setPage(1);
          }}
        />
        <Input.Search
          placeholder="按名称搜索"
          allowClear
          style={{ flex: 1 }}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onSearch={() => setPage(1)}
        />
        <span style={{ color: "#888", fontSize: 12 }}>{summary}</span>
      </div>
      {isLoading ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : items.length === 0 ? (
        <Empty description="没有匹配的素材" />
      ) : (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
              gap: 12,
            }}
          >
            {items.map((item: StockAssetListItem) => {
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
                  <StockThumb id={item.id} alt={item.name} />
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
                    title={item.name}
                  >
                    {item.name}
                    <Tag style={{ marginLeft: 4 }} color="blue">
                      {item.category}
                    </Tag>
                  </div>
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
