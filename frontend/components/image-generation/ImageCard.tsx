// frontend/components/image-generation/ImageCard.tsx
// M22 — image generation feature (T15 + T18 fix)
//
// T18 fix: replaced raw `<img src=...>` with `fetch+blob+createObjectURL` so
// the Authorization header actually reaches the backend. The browser does NOT
// send `Authorization` on a plain `<img>` request, which would yield 401 for
// any thumbnail fetched with a Bearer token. This mirrors the pattern
// `DetailModal.tsx` adopted in T16 — and is the same pattern
// `frontend/app/dashboard/document/page.tsx` uses for document previews.
//
// Module header of `services/image-generation.ts` has the full rationale.
"use client";

import { useEffect, useState } from "react";
import { Card, Tag, Tooltip, Spin, Alert, Typography, App } from "antd";
import { ExclamationCircleFilled } from "@ant-design/icons";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import "dayjs/locale/zh-cn";
import type { ImageGenerationListItem } from "@/types/image-generation";
import { imageGenerationApi } from "@/services/image-generation";

dayjs.extend(relativeTime);
dayjs.locale("zh-cn");

const { Text, Paragraph } = Typography;

const MODEL_TYPE_COLORS: Record<string, string> = {
  openai: "green",
  stability: "blue",
  ollama: "orange",
  minimax: "purple",
};

export interface ImageCardProps {
  item: ImageGenerationListItem;
  apiBase: string;
  accessToken: string;
  onClick: () => void;
}

export function ImageCard({ item, apiBase, accessToken, onClick }: ImageCardProps) {
  const { message } = App.useApp();
  const [thumbUrl, setThumbUrl] = useState<string | null>(null);

  // Fetch thumbnail bytes with the Bearer token and expose them as a blob URL.
  // Browsers won't send `Authorization` on a raw <img src=...> request, so the
  // request would 401 without this dance. Same approach as DetailModal.
  useEffect(() => {
    if (item.status !== "completed" || !item.has_thumbnail) {
      setThumbUrl(null);
      return;
    }

    let cancelled = false;
    fetch(`${apiBase}${imageGenerationApi.thumbnailPath(item.id)}`, {
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    })
      .then((r) => {
        if (!r.ok) throw new Error(`thumbnail fetch failed: ${r.status}`);
        return r.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        setThumbUrl(URL.createObjectURL(blob));
      })
      .catch(() => {
        if (cancelled) return;
        setThumbUrl(null);
        // Don't toast on every failed card — the overlay already shows a state.
        // Just leave thumbUrl null; AntD will render the placeholder background.
        if (typeof window !== "undefined") {
          // eslint-disable-next-line no-console
          if (process.env.NODE_ENV === "development") {
            console.warn(`image-gen card ${item.id}: thumbnail fetch failed`);
          }
        }
      });

    return () => {
      cancelled = true;
      setThumbUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return null;
      });
    };
    // Re-fetch when token or id changes (token rotation after 401 reload).
  }, [apiBase, accessToken, item.id, item.status, item.has_thumbnail]);

  return (
    <Card
      hoverable
      onClick={onClick}
      cover={
        <div
          style={{
            position: "relative",
            width: "100%",
            paddingTop: "100%",
            background: "#f0f0f0",
            overflow: "hidden",
          }}
        >
          {item.status === "completed" && item.has_thumbnail && thumbUrl && (
            <img
              src={thumbUrl}
              alt={item.prompt_preview}
              style={{
                position: "absolute",
                top: 0, left: 0, width: "100%", height: "100%",
                objectFit: "cover",
              }}
            />
          )}
          {item.status === "pending" || item.status === "generating" ? (
            <div
              style={{
                position: "absolute", top: 0, left: 0,
                width: "100%", height: "100%",
                display: "flex", alignItems: "center", justifyContent: "center",
                background: "rgba(0,0,0,0.4)", color: "#fff", flexDirection: "column",
              }}
            >
              <Spin />
              <div style={{ marginTop: 8 }}>生成中...</div>
            </div>
          ) : null}
          {item.status === "failed" && (
            <div
              style={{
                position: "absolute", top: 0, left: 0,
                width: "100%", height: "100%",
                display: "flex", alignItems: "center", justifyContent: "center",
                background: "rgba(255,0,0,0.1)",
              }}
            >
              <Alert
                type="error"
                icon={<ExclamationCircleFilled />}
                message="生成失败"
                style={{ background: "transparent" }}
              />
            </div>
          )}
        </div>
      }
    >
      <Tooltip title={item.prompt_preview}>
        <Paragraph
          ellipsis={{ rows: 2 }}
          style={{ marginBottom: 8, minHeight: 44 }}
        >
          {item.prompt_preview}
        </Paragraph>
      </Tooltip>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Tag color={MODEL_TYPE_COLORS[item.model_type] || "default"}>
          {item.model_name}
        </Tag>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {dayjs(item.created_at).fromNow()} · {item.size}
        </Text>
      </div>
    </Card>
  );
}
