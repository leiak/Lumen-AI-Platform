"use client";

// frontend/app/dashboard/videos/page.tsx
// M36.1 — /dashboard/videos main page.
//
// Mirrors image-generation/page.tsx structure: toolbar (status filter +
// refresh + new-compose) + responsive card grid + pagination + auto-refresh
// every 5s to pick up background FFmpeg completions.

import { useState } from "react";
import {
  Button,
  Select,
  List,
  Pagination,
  Empty,
  Tag,
  Space,
  Popconfirm,
  App,
} from "antd";
import { PlusOutlined, StopOutlined, DownloadOutlined, DeleteOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import {
  listVideos,
  cancelVideo,
  deleteVideo,
  buildVideoUrl,
  type VideoListParams,
} from "@/services/video";
import { VideoCard } from "@/components/video/VideoCard";
import { ComposeModal } from "@/components/video/ComposeModal";
import { DetailModal } from "@/components/video/DetailModal";
import type { VideoDetail, VideoStatus } from "@/types/video";

const PAGE_SIZE = 12;

const STATUS_OPTIONS: { value: VideoStatus; label: string }[] = [
  { value: "pending", label: "排队中" },
  { value: "composing", label: "合成中" },
  { value: "completed", label: "已完成" },
  { value: "failed", label: "失败" },
  { value: "cancelled", label: "已取消" },
];

export default function VideosPage() {
  const [params, setParams] = useState<VideoListParams>({ page: 1, page_size: PAGE_SIZE });
  const [composeOpen, setComposeOpen] = useState(false);
  const [detailId, setDetailId] = useState<number | null>(null);
  const qc = useQueryClient();
  const { message } = App.useApp();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["videos", params],
    queryFn: () => listVideos(params),
    // Auto-refresh every 5s — cheap, indexed by created_at, picks up
    // pending → composing → completed transitions without manual refresh.
    refetchInterval: 5000,
  });

  const { data: detail } = useQuery<VideoDetail | null>({
    queryKey: ["videos", detailId],
    queryFn: async () => {
      // 直接 fetch detail —— 不走 listVideos 的 envelope 解包。
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:11335/api/v1"}/videos/${detailId}`,
        {
          headers: {
            Authorization: `Bearer ${typeof window !== "undefined" ? localStorage.getItem("access_token") || "" : ""}`,
          },
        }
      );
      const body = await res.json();
      return body.data ?? null;
    },
    enabled: detailId !== null,
  });

  const cancelMut = useMutation({
    mutationFn: (id: number) => cancelVideo(id),
    onSuccess: () => {
      message.success("已请求取消");
      qc.invalidateQueries({ queryKey: ["videos"] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteVideo(id),
    onSuccess: () => {
      message.success("已删除");
      qc.invalidateQueries({ queryKey: ["videos"] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginTop: 0 }}>视频合成</h2>
      <div
        style={{
          marginBottom: 16,
          display: "flex",
          gap: 8,
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        <Select
          placeholder="状态"
          allowClear
          style={{ width: 140 }}
          onChange={(v) =>
            setParams({ ...params, page: 1, status: (v as VideoStatus) || undefined })
          }
          options={STATUS_OPTIONS}
        />
        <Button onClick={() => refetch()}>刷新</Button>
        <div style={{ flex: 1 }} />
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setComposeOpen(true)}
        >
          新建合成
        </Button>
      </div>

      {isLoading ? (
        <div style={{ textAlign: "center", padding: 60 }}>加载中…</div>
      ) : !data || data.items.length === 0 ? (
        <Empty description="还没有合成记录,点右上角「新建合成」试试" />
      ) : (
        <>
          <List
            grid={{ xs: 1, sm: 2, md: 3, lg: 4, gutter: 16 }}
            dataSource={data.items}
            renderItem={(item) => {
              const canCancel =
                item.status === "pending" || item.status === "composing";
              return (
                <List.Item>
                  <div
                    style={{
                      border: "1px solid #f0f0f0",
                      borderRadius: 8,
                      padding: 12,
                      background: "#fff",
                    }}
                  >
                    <VideoCard
                      item={item}
                      onClick={() => setDetailId(item.id)}
                    />
                    <div style={{ marginTop: 8, fontSize: 12, color: "#666" }}>
                      <Space size={4}>
                        <Tag>{item.resolution}</Tag>
                        <Tag>{item.fps} fps</Tag>
                        <Tag color="blue">{item.image_count} 张图</Tag>
                        <Tag color="green">
                          {(item.file_size / 1024).toFixed(0)} KB
                        </Tag>
                      </Space>
                    </div>
                    <div style={{ marginTop: 8, textAlign: "right" }}>
                      <Space size={4}>
                        {canCancel && (
                          <Popconfirm
                            title="确定取消?"
                            okText="取消"
                            cancelText="返回"
                            onConfirm={(e) => {
                              e?.stopPropagation();
                              cancelMut.mutate(item.id);
                            }}
                            onCancel={(e) => e?.stopPropagation()}
                          >
                            <Button
                              size="small"
                              icon={<StopOutlined />}
                              onClick={(e) => e.stopPropagation()}
                              loading={cancelMut.isPending}
                            >
                              取消
                            </Button>
                          </Popconfirm>
                        )}
                        {item.status === "completed" && (
                          <Button
                            size="small"
                            type="link"
                            icon={<DownloadOutlined />}
                            onClick={(e) => {
                              e.stopPropagation();
                              window.open(buildVideoUrl(item.id), "_blank");
                            }}
                          >
                            下载
                          </Button>
                        )}
                        <Popconfirm
                          title="确定删除?"
                          okText="删除"
                          okButtonProps={{ danger: true }}
                          cancelText="返回"
                          onConfirm={(e) => {
                            e?.stopPropagation();
                            deleteMut.mutate(item.id);
                          }}
                          onCancel={(e) => e?.stopPropagation()}
                        >
                          <Button
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            onClick={(e) => e.stopPropagation()}
                            loading={deleteMut.isPending}
                          />
                        </Popconfirm>
                      </Space>
                    </div>
                  </div>
                </List.Item>
              );
            }}
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

      <ComposeModal
        open={composeOpen}
        onClose={() => setComposeOpen(false)}
      />
      <DetailModal
        open={detailId !== null}
        detail={detail || null}
        onClose={() => setDetailId(null)}
      />
    </div>
  );
}