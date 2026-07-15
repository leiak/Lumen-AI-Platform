// frontend/app/dashboard/image-generation/page.tsx
// M22 — image generation feature (T18)
//
// Spec: docs/superpowers/specs/2026-06-11-image-generation-design.md §5.1, §5.2
//
// Main page: toolbar (search + status filter + refresh + new generation) +
// responsive card grid + pagination + auto-refresh every 5s to pick up
// background task completions. Clicking a card opens DetailModal (T16).
// The "新建生成" button opens CreateFormModal (T17).
//
// Env note: the project's `.env.local` exposes the API base as
// `NEXT_PUBLIC_API_URL` (not `NEXT_PUBLIC_API_BASE` as the plan template
// used). See services/chat.ts and services/auth.ts for the established name.
"use client";

import { useState } from "react";
import { Button, Input, Select, List, Pagination, Empty } from "antd";
import { PlusOutlined, SearchOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { imageGenerationApi, type ListParams } from "@/services/image-generation";
import { ImageCard } from "@/components/image-generation/ImageCard";
import { CreateFormModal } from "@/components/image-generation/CreateFormModal";
import { DetailModal } from "@/components/image-generation/DetailModal";
import type { ImageGenerationDetail } from "@/types/image-generation";

const PAGE_SIZE = 12;

// Established project-wide env var name (see services/auth.ts line 5).
const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:11335/api/v1";

export default function ImageGenerationPage() {
  const [params, setParams] = useState<ListParams>({ page: 1, page_size: PAGE_SIZE });
  const [search, setSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [detailId, setDetailId] = useState<number | null>(null);

  // The detail modal needs a valid Bearer token to fetch its full image bytes
  // (see DetailModal.tsx / T16). Read it once per render — if the token
  // rotates (401 interceptor triggers a reload), the whole page remounts and
  // we re-read it. `typeof window` guard is for SSR safety.
  const accessToken =
    typeof window !== "undefined"
      ? localStorage.getItem("access_token") || ""
      : "";

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["image-generation", params],
    queryFn: () => imageGenerationApi.list(params),
    // Auto-refresh every 5s to pick up background task completions. Cheap on
    // the backend (paginated list, indexed by created_at) and gives the user
    // a live view without having to click 刷新 manually. The CreateFormModal
    // also invalidates this key on submit, so the first poll after a new
    // task will include it.
    refetchInterval: 5000,
  });

  const { data: detail } = useQuery<ImageGenerationDetail | null>({
    queryKey: ["image-generation", detailId],
    queryFn: () => imageGenerationApi.get(detailId!),
    enabled: detailId !== null,
  });

  return (
    <div style={{ padding: 24 }}>
      <div
        style={{
          marginBottom: 16,
          display: "flex",
          gap: 8,
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        <Input
          placeholder="搜索 prompt"
          allowClear
          prefix={<SearchOutlined />}
          style={{ width: 240 }}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onPressEnter={() =>
            setParams({ ...params, page: 1, prompt: search || undefined })
          }
        />
        <Select
          placeholder="状态"
          allowClear
          style={{ width: 140 }}
          onChange={(v) => setParams({ ...params, page: 1, status: v })}
          options={[
            { value: "pending", label: "进行中" },
            { value: "completed", label: "已完成" },
            { value: "failed", label: "失败" },
          ]}
        />
        <Button onClick={() => refetch()}>刷新</Button>
        <div style={{ flex: 1 }} />
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setCreateOpen(true)}
        >
          新建生成
        </Button>
      </div>

      {isLoading ? (
        <div style={{ textAlign: "center", padding: 60 }}>加载中...</div>
      ) : !data || data.items.length === 0 ? (
        <Empty description="还没有图片,点右上角新建生成试试" />
      ) : (
        <>
          <List
            grid={{ xs: 1, sm: 2, md: 3, lg: 4, gutter: 16 }}
            dataSource={data.items}
            renderItem={(item) => (
              <List.Item>
                <ImageCard
                  item={item}
                  apiBase={API_BASE}
                  accessToken={accessToken}
                  onClick={() => setDetailId(item.id)}
                />
              </List.Item>
            )}
          />
          <div style={{ marginTop: 16, textAlign: "right" }}>
            <Pagination
              current={params.page}
              pageSize={params.page_size}
              total={data.total}
              showSizeChanger
              onChange={(page, page_size) =>
                setParams({ ...params, page, page_size })
              }
            />
          </div>
        </>
      )}

      <CreateFormModal open={createOpen} onClose={() => setCreateOpen(false)} />
      <DetailModal
        open={detailId !== null}
        detail={detail || null}
        apiBase={API_BASE}
        onClose={() => setDetailId(null)}
      />
    </div>
  );
}
