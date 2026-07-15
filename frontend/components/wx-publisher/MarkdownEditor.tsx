// frontend/components/wx-publisher/MarkdownEditor.tsx
// M32.1 — 公众号助手 — Markdown 编辑器 (中间列).
//
// 升级:从 antd `Input.TextArea` 替换为 `@uiw/react-md-editor`, 借鉴
// lark-to-markdown-main/components/EditorPanel.tsx。
// - 内置工具栏 (粗体/斜体/标题/链接/图片/代码块/表格/列表/引用)
// - 完整 Markdown 编辑体验 (语法高亮 + 快捷键)
// - preview="edit" + previewOptions.display="none" 关掉自带预览
//   (右侧 RenderPreview 走 iframe 真实模板预览)
// - textareaProps.onPaste 钩子给 useHtmlPasteHandler 用
// - 顶部渐变 logo 区(同 lark 「飞书文档转公众号」风格)
"use client";

import { useEffect, useState, type ClipboardEvent } from "react";
import dynamic from "next/dynamic";
import { FileTextOutlined } from "@ant-design/icons";
import "@uiw/react-md-editor/markdown-editor.css";

// 动态 import 防 SSR (@uiw/react-md-editor 内部用 DOM API)
const MDEditor = dynamic(
  () => import("@uiw/react-md-editor").then((m) => m.default),
  { ssr: false, loading: () => <div style={{ height: 500 }} /> }
);

interface MarkdownEditorProps {
  content: string;
  renderedHtml?: string | null;
  onChange?: (value: string) => void;
  onPasteHtml?: (e: ClipboardEvent<HTMLTextAreaElement>) => void;
  height?: number;
}

export function MarkdownEditor({
  content,
  onChange,
  onPasteHtml,
  height = 500,
}: MarkdownEditorProps) {
  // 'mounted' flag 防 SSR mismatch(@uiw/react-md-editor 用 localStorage)
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  return (
    <div
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 6,
        overflow: "hidden",
        background: "#fff",
      }}
    >
      {/* 顶部渐变 logo 区 — 借鉴 lark 「飞书文档转公众号」视觉锚点 */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "10px 16px",
          background: "linear-gradient(135deg, #2563eb 0%, #9333ea 100%)",
          color: "#fff",
        }}
      >
        <FileTextOutlined style={{ fontSize: 18 }} />
        <span style={{ fontSize: 16, fontWeight: 700 }}>公众号助手</span>
        <span style={{ fontSize: 12, opacity: 0.85 }}>编辑器</span>
        <span
          style={{
            marginLeft: "auto",
            fontSize: 11,
            opacity: 0.85,
            fontWeight: 400,
          }}
        >
          支持粘贴飞书/网页富文本 → 自动转 Markdown
        </span>
      </div>
      {mounted && (
        <MDEditor
          value={content}
          onChange={(v) => onChange?.(v ?? "")}
          height={height}
          preview="edit"
          hideToolbar={false}
          visibleDragbar={false}
          enableScroll
          previewOptions={{
            style: { display: "none" }, // 关自带预览, 右侧 RenderPreview 已接管
          }}
          textareaProps={{
            placeholder:
              "在此输入 Markdown,或粘贴飞书/网页富文本自动转换...",
            onPaste: onPasteHtml,
          }}
          data-color-mode="light"
        />
      )}
    </div>
  );
}

export default MarkdownEditor;