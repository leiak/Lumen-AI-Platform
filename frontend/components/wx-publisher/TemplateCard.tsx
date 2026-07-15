// frontend/components/wx-publisher/TemplateCard.tsx
// M32 — 公众号助手 — Template gallery card.
//
// Spec §5.4 — Card 网格, 每张卡: 缩略图 (1:1 cover) + 模板名 + 分类 Tag +
// 应用按钮. 系统模板 (is_system=true) 用灰色边框 + 角标.
//
// M32.1: 加「生成缩略图」按钮 — 当 thumbnailUrl 未提供时, 用户可点
// 触发 image-generation API 自动生成. 用 App.useApp() 弹 toast.
//
// M32.1 follow-up: 缩略图走 fetch + blob + URL.createObjectURL 而非
// ``<img src=...>``, 原因同 M22 image-generation DetailModal —
// ``<img>`` 标签不能设 Authorization 头, 后端用 Bearer auth 会 401.
// 之前父页面用 ``?token=xxx`` query string 传 token, 后端不认 (401),
// 导致所有 15 张图都退到 alt 文字占位. 现在每张卡自己 fetch 一次
// (后端 ETag + Cache-Control: private, max-age=300, 二次访问命中),
// mount 时拿到 blob URL, unmount 时 revokeObjectURL 释放.
"use client";

import { useEffect, useState } from "react";
import { Card, Tag, Button, Space, Tooltip, App } from "antd";
import {
  PictureOutlined,
  AppstoreOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import type { WxTemplateListItem } from "@/types/wx-publisher";
import { templateApi } from "@/services/wx-publisher";

interface TemplateCardProps {
  template: WxTemplateListItem;
  /** 缩略图生成后的回调 — 父组件刷新 thumbnail URL */
  onThumbnailGenerated?: (templateId: number) => void;
  onApply: (template: WxTemplateListItem) => void;
  onPreview?: (template: WxTemplateListItem) => void;
}

// 5 种类别的本地化标签, 与 spec §3.2 对齐.
const CATEGORY_LABELS: Record<string, string> = {
  minimal: "极简",
  tech: "科技",
  magazine: "杂志",
  literary: "文艺",
  business: "商务",
};

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:11335/api/v1";

export function TemplateCard({
  template,
  onThumbnailGenerated,
  onApply,
  onPreview,
}: TemplateCardProps) {
  const { message: toast } = App.useApp();
  const [genLoading, setGenLoading] = useState(false);
  // blob URL (URL.createObjectURL result) — 用 effect 内部 fetch + blob
  // 拿到 bytes 后赋值. 失败时 null, 退回 PictureOutlined 占位.
  const [thumbBlobUrl, setThumbBlobUrl] = useState<string | null>(null);
  const categoryLabel = CATEGORY_LABELS[template.category] ?? template.category;

  // Fetch thumbnail bytes (Bearer-auth) → blob URL. Re-runs when
  // ``has_thumbnail`` flips to true (e.g. user clicks 「生成缩略图」 and
  // parent refetches the list). Cleanup revokes the previous blob URL.
  useEffect(() => {
    if (!template.has_thumbnail) {
      setThumbBlobUrl(null);
      return;
    }
    let cancelled = false;
    const token =
      typeof window !== "undefined"
        ? localStorage.getItem("access_token")
        : null;
    fetch(`${API_BASE}${templateApi.thumbnailPath(template.id)}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => {
        if (!r.ok) throw new Error(`thumbnail fetch failed: ${r.status}`);
        return r.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        setThumbBlobUrl(URL.createObjectURL(blob));
      })
      .catch(() => {
        if (cancelled) return;
        setThumbBlobUrl(null);
      });
    return () => {
      cancelled = true;
      setThumbBlobUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return null;
      });
    };
  }, [template.id, template.has_thumbnail]);

  const handleGenerate = async () => {
    setGenLoading(true);
    try {
      await templateApi.generateThumbnail(template.id);
      toast.success("缩略图已生成");
      onThumbnailGenerated?.(template.id);
    } catch (err: any) {
      toast.error(err?.message || "生成失败");
    } finally {
      setGenLoading(false);
    }
  };

  return (
    <Card
      hoverable
      size="small"
      styles={{
        body: { padding: 12 },
      }}
      style={{
        borderColor: template.is_system ? "#bfbfbf" : undefined,
        position: "relative",
      }}
      cover={
        <div
          style={{
            height: 160,
            background: "#f5f5f5",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            overflow: "hidden",
          }}
        >
          {thumbBlobUrl ? (
            <img
              src={thumbBlobUrl}
              alt={template.name}
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
            />
          ) : (
            <PictureOutlined style={{ fontSize: 36, color: "#bfbfbf" }} />
          )}
        </div>
      }
    >
      {template.is_system && (
        <Tag
          color="default"
          style={{
            position: "absolute",
            top: 8,
            right: 8,
            background: "rgba(255,255,255,0.9)",
          }}
        >
          系统
        </Tag>
      )}
      <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 6 }}>
        {template.name}
      </div>
      <Space size={4} wrap style={{ marginBottom: 8 }}>
        <Tag color="blue">{categoryLabel}</Tag>
        <Tooltip title="使用次数">
          <Tag icon={<AppstoreOutlined />}>{template.usage_count}</Tag>
        </Tooltip>
      </Space>
      {template.description && (
        <div
          style={{
            fontSize: 12,
            color: "#666",
            marginBottom: 8,
            minHeight: 32,
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          {template.description}
        </div>
      )}
      <Space size={4} wrap>
        <Button
          type="primary"
          size="small"
          onClick={() => onApply(template)}
        >
          应用
        </Button>
        {onPreview && (
          <Button size="small" onClick={() => onPreview(template)}>
            预览
          </Button>
        )}
        {/* M32.1: 用 image-generation 自动生成缩略图 — 只在没有 thumbnail 时显示 */}
        {!template.has_thumbnail && (
          <Button
            size="small"
            icon={<ThunderboltOutlined />}
            loading={genLoading}
            onClick={handleGenerate}
            title="用 image-generation 自动生成缩略图"
          >
            生成缩略图
          </Button>
        )}
      </Space>
    </Card>
  );
}

export default TemplateCard;
