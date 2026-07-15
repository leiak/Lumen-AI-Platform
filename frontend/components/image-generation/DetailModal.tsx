// frontend/components/image-generation/DetailModal.tsx
// M22 — image generation feature (T16)
//
// Spec: docs/superpowers/specs/2026-06-11-image-generation-design.md §5.1
//
// IMPORTANT (T15 review feedback): a plain <img src=...> will get a 401 because
// `services/auth.ts` does NOT set `withCredentials: true`, and browsers do not
// send the Authorization header on <img> requests. We must fetch + blob +
// URL.createObjectURL instead. See `frontend/services/image-generation.ts`
// module header for the full rationale and `frontend/app/dashboard/document/page.tsx`
// for the established pattern in this project.
"use client";

import { useEffect, useState } from "react";
import { Modal, Descriptions, Button, Popconfirm, message, Tag, Typography, Space, Alert } from "antd";
import { RedoOutlined, DownloadOutlined, DeleteOutlined } from "@ant-design/icons";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { imageGenerationApi } from "@/services/image-generation";
import type { ImageGenerationDetail } from "@/types/image-generation";

const { Paragraph } = Typography;

export interface DetailModalProps {
  open: boolean;
  detail: ImageGenerationDetail | null;
  apiBase: string;
  onClose: () => void;
}

export function DetailModal({ open, detail, apiBase, onClose }: DetailModalProps) {
  const qc = useQueryClient();
  const [imgUrl, setImgUrl] = useState<string | null>(null);

  const regenMut = useMutation({
    mutationFn: (id: number) => imageGenerationApi.regenerate(id),
    onSuccess: () => {
      message.success("已重新生成");
      qc.invalidateQueries({ queryKey: ["image-generation"] });
      onClose();
    },
    onError: (e: Error) => message.error(e.message),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => imageGenerationApi.delete(id),
    onSuccess: () => {
      message.success("已删除");
      qc.invalidateQueries({ queryKey: ["image-generation"] });
      onClose();
    },
    onError: (e: Error) => message.error(e.message),
  });

  // Fetch image bytes with Authorization header, then expose as blob URL.
  // Plain <img src=...> cannot send the Bearer token.
  useEffect(() => {
    if (!open || !detail || detail.status !== "completed") {
      setImgUrl(null);
      return;
    }

    let cancelled = false;
    const token =
      typeof window !== "undefined" ? localStorage.getItem("access_token") : null;

    fetch(`${apiBase}${imageGenerationApi.imagePath(detail.id)}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => {
        if (!r.ok) throw new Error(`image fetch failed: ${r.status}`);
        return r.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        setImgUrl(URL.createObjectURL(blob));
      })
      .catch(() => {
        if (cancelled) return;
        setImgUrl(null);
        message.error("图片加载失败");
      });

    return () => {
      cancelled = true;
      setImgUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return null;
      });
    };
  }, [open, detail?.id, detail?.status, apiBase]);

  if (!detail) return null;

  return (
    <Modal
      open={open}
      onCancel={onClose}
      width={900}
      footer={null}
      title="图片详情"
      destroyOnHidden
    >
      <div style={{ display: "flex", gap: 16 }}>
        <div style={{ flex: 1, textAlign: "center", maxHeight: "70vh", overflow: "auto" }}>
          {imgUrl && (
            <img
              src={imgUrl}
              alt={detail.prompt}
              style={{ maxWidth: "100%", maxHeight: "70vh" }}
            />
          )}
          {detail.status === "failed" && detail.error_message && (
            <Alert type="error" message={detail.error_message} />
          )}
        </div>
        <div style={{ flex: 1 }}>
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="模型">
              {detail.model_name} <Tag>{detail.model_type}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Prompt">
              <Paragraph copyable style={{ whiteSpace: "pre-wrap" }}>{detail.prompt}</Paragraph>
            </Descriptions.Item>
            {detail.negative_prompt && (
              <Descriptions.Item label="负向 Prompt">
                <Paragraph copyable>{detail.negative_prompt}</Paragraph>
              </Descriptions.Item>
            )}
            <Descriptions.Item label="尺寸">{detail.size}</Descriptions.Item>
            <Descriptions.Item label="质量">{detail.quality || "-"}</Descriptions.Item>
            <Descriptions.Item label="风格">{detail.style || "-"}</Descriptions.Item>
            <Descriptions.Item label="数量">{detail.n}</Descriptions.Item>
            <Descriptions.Item label="耗时">
              {detail.duration_ms ? `${detail.duration_ms} ms` : "-"}
            </Descriptions.Item>
            {detail.params && (
              <Descriptions.Item label="完整参数">
                <pre style={{ maxHeight: 200, overflow: "auto", fontSize: 12 }}>
                  {JSON.stringify(detail.params, null, 2)}
                </pre>
              </Descriptions.Item>
            )}
          </Descriptions>
        </div>
      </div>
      <div style={{ marginTop: 16, textAlign: "right" }}>
        <Space>
          <Button
            icon={<RedoOutlined />}
            loading={regenMut.isPending}
            onClick={() => regenMut.mutate(detail.id)}
          >
            重新生成
          </Button>
          {detail.status === "completed" && (
            <Button
              icon={<DownloadOutlined />}
              disabled={!imgUrl}
              onClick={() => {
                if (!imgUrl) return;
                const a = document.createElement("a");
                a.href = imgUrl;
                a.download = `image-${detail.id}.png`;
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
