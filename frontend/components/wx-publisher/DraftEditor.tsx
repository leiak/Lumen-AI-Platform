// frontend/components/wx-publisher/DraftEditor.tsx
// M32 — 公众号助手 — 草稿编辑器 3 列布局容器.
//
// Spec §5.3 — 24 grid: 6 + 12 + 6.
//   左: SectionTree (章节树)
//   中: MarkdownEditor
//   右: RenderPreview (iframe, 节流 500ms)
// 顶部 Header 由 page-level 提供; 该组件聚焦布局 + 节流.
"use client";

import { useEffect, useRef, useState } from "react";
import type { ClipboardEvent } from "react";
import { Row, Col, Space, Tag, Card } from "antd";
import { SectionTree } from "./SectionTree";
import { MarkdownEditor } from "./MarkdownEditor";
import { RenderPreview } from "./RenderPreview";
import type { WxDraftSectionResponse } from "@/types/wx-publisher";

const PREVIEW_DEBOUNCE_MS = 500;
const STATUS_COLOR: Record<string, string> = {
  draft: "default",
  rendering: "processing",
  ready: "cyan",
  publishing: "blue",
  published: "success",
  failed: "error",
};

interface DraftEditorProps {
  sections: WxDraftSectionResponse[];
  activeSectionId?: number | null;
  content: string;
  renderedHtml?: string | null;
  status?: string;
  onSelectSection?: (id: number) => void;
  onAddSection?: () => void;
  onAiOutline?: () => void;
  onRewrite?: (id: number) => void;
  onExpand?: (id: number) => void;
  onDeleteSection?: (id: number) => void;
  onContentChange?: (value: string) => void;
  onPasteHtml?: (e: ClipboardEvent<HTMLTextAreaElement>) => void;
  /** 2026-06-29 — 「插入素材」按钮回调,page-level 打开 MaterialPickerModal。 */
  onInsertMaterial?: () => void;
}

export function DraftEditor({
  sections,
  activeSectionId,
  content,
  renderedHtml,
  status,
  onSelectSection,
  onAddSection,
  onAiOutline,
  onRewrite,
  onExpand,
  onDeleteSection,
  onContentChange,
  onPasteHtml,
  onInsertMaterial,
}: DraftEditorProps) {
  // 节流 500ms 实时预览 — 仅当 content 变化才推进到 debouncedContent,
  // RenderPreview 拿 debouncedContent 渲染, 避免每个 keyup 重建 iframe.
  // 首次 render 立即同步 (跳过 debounce) — 否则初始 content 为空时 preview 永远空.
  const [debouncedContent, setDebouncedContent] = useState(content);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isFirstRender = useRef(true);

  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      setDebouncedContent(content);
      return;
    }
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      setDebouncedContent(content);
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [content]);

  // 渲染预览优先用后端 content_html (模板渲染产物); 没有则用 markdown
  // (MVP 简版 — 真渲染走 /render endpoint, 这里做 fallback).
  const previewHtml = renderedHtml ?? (debouncedContent
    ? `<pre style="font-family:monospace;white-space:pre-wrap;">${escapeHtml(debouncedContent)}</pre>`
    : null);

  return (
    <Row gutter={12}>
      <Col span={6}>
        <Card
          size="small"
          title={status ? <Tag color={STATUS_COLOR[status] ?? "default"}>{status}</Tag> : "章节"}
          styles={{ body: { padding: 0, maxHeight: 600, overflowY: "auto" } }}
        >
          <SectionTree
            sections={sections}
            activeId={activeSectionId}
            onSelect={onSelectSection}
            onAddSection={onAddSection}
            onAiOutline={onAiOutline}
            onRewrite={onRewrite}
            onExpand={onExpand}
            onDelete={onDeleteSection}
            onInsertMaterial={onInsertMaterial}
          />
        </Card>
      </Col>
      <Col span={12}>
        <Card size="small" styles={{ body: { padding: 8 } }}>
          <MarkdownEditor
            content={content}
            renderedHtml={renderedHtml}
            onChange={onContentChange}
            onPasteHtml={onPasteHtml}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card size="small" title="实时预览" styles={{ body: { padding: 8 } }}>
          <RenderPreview html={previewHtml} />
        </Card>
      </Col>
    </Row>
  );
}

// 简易 HTML escape — 防 XSS, 同时保留换行.
function escapeHtml(s: string) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export default DraftEditor;