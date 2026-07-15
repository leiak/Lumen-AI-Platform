// frontend/components/wx-publisher/HtmlPasteHandler.tsx
// M32.1 — 公众号助手 — 粘贴飞书/网页 HTML 自动转 Markdown.
//
// 借鉴 lark-to-markdown-main/components/EditorPanel.tsx 的 paste 钩子
// + utils/markdownConverter.ts 的后端转换。
//
// 行为:
// 1. 用户在 MDEditor Ctrl+V 粘贴内容
// 2. 拦截 paste 事件,读 clipboardData.getData("text/html")
// 3. 启发:html 长度 > text 长度 1.5x 才值得转(纯文本粘贴不触发)
// 4. e.preventDefault() 阻止默认行为
// 5. 调 draftApi.pasteHtml 后端转 MD
// 6. onConverted 回调把转换后的全文传给父组件更新 content
//
// 复用 useHtmlPasteHandler hook, 不破坏 MarkdownEditor 的纯展示组件边界。
"use client";

import { useCallback } from "react";
import { App } from "antd";
import type { ClipboardEvent } from "react";
import { draftApi } from "@/services/wx-publisher";

// 200KB 提示 — html 过大可能转换慢,前端先提示
const PASTE_WARN_BYTES = 200_000;

export interface UseHtmlPasteHandlerArgs {
  draftId: number;
  /** 转换后回调:把后端返回的全文 content_markdown 传给父组件 */
  onConverted: (fullMarkdown: string) => void;
}

export function useHtmlPasteHandler({
  draftId,
  onConverted,
}: UseHtmlPasteHandlerArgs) {
  const { message } = App.useApp();
  return useCallback(
    async (e: ClipboardEvent<HTMLTextAreaElement>) => {
      const html = e.clipboardData.getData("text/html");
      if (!html) return; // 纯文本粘贴,让默认 paste 走
      const text = e.clipboardData.getData("text/plain");
      // 启发:html 比 text 长 1.5x 以上才值得走转换(否则就是普通富文本粘贴)
      if (!text || html.length < text.length * 1.5) return;
      e.preventDefault();
      if (html.length > PASTE_WARN_BYTES) {
        message.warning(
          `粘贴内容较大(${Math.round(html.length / 1024)}KB),转换可能稍慢`
        );
      }
      try {
        const res = await draftApi.pasteHtml(draftId, { html });
        onConverted(res.content_markdown ?? "");
        message.success("已粘贴并转换为 Markdown");
      } catch (err: any) {
        message.error(err?.message || "粘贴转换失败");
      }
    },
    [draftId, onConverted, message]
  );
}