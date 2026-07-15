"use client";

import { Component, ReactNode, useState } from "react";
import { Alert, Collapse, Dropdown, Tag, Tooltip, message as antdMessage } from "antd";
import {
  CaretRightOutlined,
  CopyOutlined,
  CheckOutlined,
  FileWordOutlined,
  FilePdfOutlined,
  FileMarkdownOutlined,
  WarningOutlined,
  DownOutlined,
} from "@ant-design/icons";
import { Markdown } from "./Markdown";
import { Citations } from "./Citations";
import { AttachmentChip } from "./AttachmentChip";
import type { Message, CitationSource } from "@/types/chat";
// markdownToDocx is loaded lazily inside handleExportWord to keep the
// chat page initial bundle slim (the docx library is ~600KB).

interface MessageBubbleProps {
  message: Message;
}

/**
 * ErrorBoundary around <Markdown />: react-markdown 9 re-parses on
 * every render and can throw on pathological inputs (e.g. an unclosed
 * table or fenced code block in mid-stream). Without a boundary the
 * whole bubble would disappear, leaving an empty message — confusing
 * for the user. Falling back to <pre> preserves the raw text so the
 * content is still readable even if formatting is lost.
 */
class MarkdownBoundary extends Component<
  { content: string; children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  componentDidCatch(error: Error) {
    // M30 P0-3: dev-only — production should silently use the
    // boundary's plain-text fallback (UI is already designed for it).
    // eslint-disable-next-line no-console
    if (process.env.NODE_ENV === "development") {
      console.warn("[MarkdownBoundary] falling back to plain text:", error);
    }
  }
  render() {
    if (this.state.hasError) {
      return (
        <pre
          style={{
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            fontFamily: "inherit",
            margin: 0,
          }}
        >
          {this.props.content}
        </pre>
      );
    }
    return this.props.children;
  }
}

interface ParsedContent {
  thinking: string | null;
  answer: string;
}

/**
 * Parse out `<think>...</think>` (or `<thinking>...</thinking>`)
 * blocks from a streamed LLM response.
 */
function parseThinkingContent(content: string): ParsedContent {
  const thinkMatch = content.match(/<think>([\s\S]*?)<\/think>/i);
  if (thinkMatch) {
    const thinking = thinkMatch[1].trim();
    const answer = content.replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
    return { thinking, answer };
  }
  const altMatch = content.match(/<thinking>([\s\S]*?)<\/thinking>/i);
  if (altMatch) {
    const thinking = altMatch[1].trim();
    const answer = content.replace(/<thinking>[\s\S]*?<\/thinking>/gi, "").trim();
    return { thinking, answer };
  }
  return { thinking: null, answer: content };
}

/**
 * Pull citations from the message metadata. The backend (and any
 * RAG layer) can attach a `sources` array to the message's
 * metadata; the UI will render it without further plumbing.
 */
function extractSources(message: Message): CitationSource[] {
  const meta = message.metadata;
  if (!meta || typeof meta !== "object") return [];
  const raw =
    (meta as Record<string, any>).sources ||
    (meta as Record<string, any>).citations ||
    [];
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (s) => s && (s.title || s.name || s.snippet || s.content || s.url),
  );
}

/**
 * Pull attachment references from the message metadata. Attachments
 * uploaded with a user message are stored as an `attachments` array
 * on the message metadata; the UI renders one chip per attachment.
 */
function extractAttachments(message: Message) {
  const meta = message.metadata;
  if (!meta || typeof meta !== "object") return [];
  const raw = (meta as Record<string, any>).attachments;
  return Array.isArray(raw) ? raw : [];
}

/**
 * Read `metadata.search_status` set by the backend's ChatFeatureService.
 *
 *   "ok"       — provider returned results, used in answer
 *   "empty"    — provider returned 0 results (e.g. query too obscure)
 *   "error"    — provider raised an exception
 *   "disabled" — user did not toggle web search on
 *   undefined  — older message without the field
 *
 * We surface a small notice for "empty" / "error" so the user
 * understands why the answer is a generic "I cannot search" response.
 */
type SearchStatus = "ok" | "empty" | "error" | "disabled" | undefined;
function extractSearchStatus(message: Message): SearchStatus {
  const meta = message.metadata;
  if (!meta || typeof meta !== "object") return undefined;
  const s = (meta as Record<string, any>).search_status;
  if (s === "ok" || s === "empty" || s === "error" || s === "disabled") {
    return s;
  }
  return undefined;
}

/**
 * Pull skill names from the message metadata. Skill names are written
 * to msg_metadata by ChatFeatureService when skills are applied to a
 * chat request, and surfaced via the SSE done event for real-time
 * display without a DB re-fetch.
 */
function extractSkills(message: Message): string[] {
  const meta = message.metadata;
  if (!meta || typeof meta !== "object") return [];
  const raw = (meta as Record<string, any>).skills;
  return Array.isArray(raw) ? raw.filter((s) => typeof s === "string") : [];
}

/**
 * Electron's preload script exposes ``saveFile`` on
 * ``window.electronAPI``; the web build of the same code does
 * not. Typing it as optional lets the same component compile in
 * both without sprinkling `as any` casts.
 */
interface ElectronAPI {
  saveFile?: (opts: {
    defaultName: string;
    filters: Array<{ name: string; extensions: string[] }>;
    buffer: number[];
  }) => Promise<
    | { ok: true; path: string }
    | { ok: false; canceled: true }
    | { ok: false; error: string }
  >;
}
declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

/**
 * Build a deterministic, collision-resistant filename for the
 * export. ``chat-YYYYMMDD-HHmm.docx`` in local time. The same
 * minute can collide if the user exports two messages back to
 * back, which is fine — Word will prompt before overwriting.
 */
function makeExportFileName(ext: "docx" | "pdf" | "md"): string {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return `chat-${yyyy}${mm}${dd}-${hh}${min}.${ext}`;
}

/**
 * Assistant message bubble.
 * Renders the parsed thinking block (collapsible) + Markdown body +
 * citation chips + a copy-to-clipboard button for the whole message
 * + an export-to-Word button (browser download or Electron native
 * save dialog, depending on the runtime).
 */
export function MessageBubble({ message }: MessageBubbleProps) {
  const [copied, setCopied] = useState(false);
  // Track which export is in flight, not just whether anything is
  // exporting. The dropdown items disable individually while their
  // own format is being generated; other formats stay clickable.
  const [exporting, setExporting] = useState<
    null | "word" | "pdf" | "markdown"
  >(null);

  if (message.role === "user") {
    const attachments = extractAttachments(message);
    return (
      <div>
        <div
          style={{
            padding: "12px 16px",
            borderRadius: 12,
            background: "#1890ff",
            color: "#fff",
            whiteSpace: "pre-wrap",
            wordBreak: "normal",
            overflowWrap: "break-word",
            lineHeight: 1.5,
          }}
        >
          {message.content}
        </div>
        {attachments.length > 0 && (
          <div
            style={{
              marginTop: 6,
              display: "flex",
              flexWrap: "wrap",
              justifyContent: "flex-end",
            }}
          >
            {attachments.map((a) => (
              <AttachmentChip key={a.name} attachment={a} readOnly />
            ))}
          </div>
        )}
      </div>
    );
  }

  // assistant / system
  const { thinking, answer } = parseThinkingContent(message.content || "");
  const sources = extractSources(message);
  const searchStatus = extractSearchStatus(message);
  const skills = extractSkills(message);
  const text = (answer || message.content || "").trim();

  const handleCopyAll = async () => {
    const text = (answer || message.content || "").trim();
    if (!text) return;
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopied(true);
      antdMessage.success("已复制到剪贴板");
      setTimeout(() => setCopied(false), 1500);
    } catch (e) {
      antdMessage.error("复制失败");
    }
  };

  const handleExportWord = async () => {
    const text = (answer || message.content || "").trim();
    if (!text) return;
    setExporting("word");
    try {
      const { markdownToDocx } = await import("@/lib/markdown-to-docx");
      const { downloadBuffer } = await import("@/lib/download-buffer");
      const buffer = await markdownToDocx(text);
      const result = await downloadBuffer({
        buffer,
        filename: makeExportFileName("docx"),
        mimeType:
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        electronFilters: [{ name: "Word 文档", extensions: ["docx"] }],
      });
      if (result.delivered) {
        antdMessage.success(
          result.path ? `已保存到 ${result.path}` : "Word 文档已下载",
        );
      } else if (result.error) {
        antdMessage.error(`导出失败: ${result.error}`);
      }
      // result.delivered === false && !result.error → user cancelled
    } catch (e) {
      antdMessage.error(
        `导出失败: ${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      setExporting(null);
    }
  };

  const handleExportPdf = async () => {
    const text = (answer || message.content || "").trim();
    if (!text) return;
    setExporting("pdf");
    try {
      const { downloadPdfFromBackend } = await import("@/lib/export-pdf");
      const token =
        typeof window !== "undefined"
          ? localStorage.getItem("access_token") ?? ""
          : "";
      const result = await downloadPdfFromBackend({
        text,
        filename: makeExportFileName("pdf"),
        token,
      });
      if (result.delivered) {
        antdMessage.success("PDF 文档已下载");
      } else if (result.error) {
        antdMessage.error(`导出失败: ${result.error}`);
      }
    } catch (e) {
      antdMessage.error(
        `导出失败: ${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      setExporting(null);
    }
  };

  const handleExportMarkdown = async () => {
    const text = (answer || message.content || "").trim();
    if (!text) return;
    setExporting("markdown");
    try {
      const { downloadMarkdown } = await import("@/lib/export-markdown");
      const result = await downloadMarkdown(text, makeExportFileName("md"));
      if (result.delivered) {
        antdMessage.success("Markdown 已下载");
      } else if (result.error) {
        antdMessage.error(`导出失败: ${result.error}`);
      }
    } catch (e) {
      antdMessage.error(
        `导出失败: ${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      setExporting(null);
    }
  };

  return (
    <div className="chat-bubble chat-bubble--assistant">
      {thinking && (
        <div style={{ marginBottom: 8 }}>
          <Collapse
            ghost
            expandIcon={({ isActive }) => (
              <CaretRightOutlined rotate={isActive ? 90 : 0} />
            )}
            items={[
              {
                key: "1",
                label: (
                  <span style={{ color: "#888", fontSize: 12 }}>
                    AI 思考过程
                  </span>
                ),
                children: (
                  <div
                    style={{
                      background: "#f5f5f5",
                      padding: "12px 16px",
                      borderRadius: 8,
                      fontSize: 13,
                      color: "#666",
                      fontFamily: "monospace",
                      whiteSpace: "pre-wrap",
                      lineHeight: 1.6,
                      maxHeight: 300,
                      overflow: "auto",
                    }}
                  >
                    {thinking}
                  </div>
                ),
              },
            ]}
          />
        </div>
      )}

      {answer && (
        <div
          style={{
            padding: "12px 16px",
            borderRadius: 12,
            background: "#f0f0f0",
            color: "#333",
            lineHeight: 1.5,
          }}
        >
          <MarkdownBoundary content={answer}>
            <Markdown content={answer} />
          </MarkdownBoundary>
        </div>
      )}

      {(searchStatus === "empty" || searchStatus === "error") && (
        <div data-testid="search-status-notice" style={{ marginTop: 8 }}>
          <Alert
            type={searchStatus === "error" ? "error" : "warning"}
            showIcon
            icon={<WarningOutlined />}
            message={
              searchStatus === "error"
                ? "联网搜索出错,以下回答基于模型自身知识"
                : "联网搜索未返回结果,以下回答基于模型自身知识"
            }
          />
        </div>
      )}

      {skills.length > 0 && (
        <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
          <span style={{ fontSize: 12, color: "#888", marginRight: 2 }}>技能:</span>
          {skills.map((name) => (
            <Tag key={name} color="blue" style={{ margin: 0 }}>{name}</Tag>
          ))}
        </div>
      )}

      {(answer || sources.length > 0) && (
        <div className="chat-bubble__actions">
          {sources.length > 0 && (
            <div className="chat-bubble__actions-row">
              <Citations sources={sources} />
            </div>
          )}
          <div className="chat-bubble__actions-row">
            <Tooltip title={copied ? "已复制" : "复制整条消息"}>
              <button
                type="button"
                className="chat-bubble__copy"
                onClick={handleCopyAll}
                aria-label="复制整条消息"
              >
                {copied ? <CheckOutlined /> : <CopyOutlined />}
                <span style={{ marginLeft: 4 }}>
                  {copied ? "已复制" : "复制"}
                </span>
              </button>
            </Tooltip>
            <Tooltip
              title={
                exporting === "word" ? "正在导出 Word" : "导出为 Word (.docx)"
              }
            >
              {/* Split-button: main action = Word, dropdown = PDF + Markdown.
                  Each entry gets its own loading state — only the active
                  export disables its own item; the others stay clickable
                  so the user can fire off a second export without
                  waiting for the first to finish.

                  antd's Dropdown.Button has no `buttons` prop — the main
                  (left) button uses `onClick` + `loading` + the children
                  string. Icon goes inside the children. */}
              <Dropdown.Button
                type="default"
                size="small"
                trigger={["click"]}
                icon={<DownOutlined />}
                loading={exporting === "word"}
                disabled={!text || exporting === "word"}
                onClick={() => void handleExportWord()}
                menu={{
                  items: [
                    {
                      key: "pdf",
                      label: (
                        <span>
                          <FilePdfOutlined style={{ marginRight: 6 }} />
                          导出 PDF
                        </span>
                      ),
                      disabled: exporting === "pdf" || !text,
                      onClick: () => void handleExportPdf(),
                    },
                    {
                      key: "markdown",
                      label: (
                        <span>
                          <FileMarkdownOutlined style={{ marginRight: 6 }} />
                          导出 Markdown
                        </span>
                      ),
                      disabled: exporting === "markdown" || !text,
                      onClick: () => void handleExportMarkdown(),
                    },
                  ],
                }}
              >
                <FileWordOutlined />
                <span style={{ marginLeft: 4 }}>
                  {exporting === "word" ? "导出中" : "导出 Word"}
                </span>
              </Dropdown.Button>
            </Tooltip>
          </div>
        </div>
      )}
    </div>
  );
}
