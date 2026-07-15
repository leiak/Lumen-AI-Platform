"use client";

import { useState } from "react";
import { Tooltip, Modal, Empty, Tag } from "antd";
import { FileTextOutlined, LinkOutlined } from "@ant-design/icons";
import type { CitationSource } from "@/types/chat";

interface CitationsProps {
  sources: CitationSource[];
}

/**
 * Numbered citation chips rendered below an assistant message.
 *
 * Click behavior (graceful fallback when source-open flow is incomplete):
 *  1. If `source.url` is set, open in a new tab.
 *  2. Otherwise, if `source.document_id` is set, navigate to the
 *     knowledge base document page.
 *  3. Otherwise, open a modal showing the source snippet / metadata.
 *
 * This keeps the chip clickable and useful even before the backend
 * implements the deep-link flow.
 */
export function Citations({ sources }: CitationsProps) {
  const [preview, setPreview] = useState<CitationSource | null>(null);

  if (!sources || sources.length === 0) {
    return null;
  }

  const handleClick = (src: CitationSource, idx: number) => {
    if (src.url) {
      window.open(src.url, "_blank", "noopener,noreferrer");
      return;
    }
    if (src.document_id) {
      // Best-effort navigation; if the page doesn't exist yet, the user
      // still gets the snippet modal below.
      const target = `/dashboard/knowledge?document=${src.document_id}`;
      try {
        window.open(target, "_blank");
      } catch (e) {
        // ignore
      }
    }
    // Always show the snippet modal so the chip is never a dead button.
    setPreview(sources[idx] || src);
  };

  return (
    <div className="chat-citations">
      <div className="chat-citations__label">参考来源</div>
      <div className="chat-citations__chips">
        {sources.map((src, idx) => {
          const title = src.title || src.name || `来源 ${idx + 1}`;
          const tooltipText = src.snippet || src.content || title;
          return (
            <Tooltip key={src.id ?? idx} title={tooltipText} placement="top">
              <button
                type="button"
                className="chat-citation-chip"
                onClick={() => handleClick(src, idx)}
                aria-label={`查看来源 ${idx + 1}: ${title}`}
              >
                <span className="chat-citation-chip__index">{idx + 1}</span>
                <FileTextOutlined style={{ marginRight: 4 }} />
                <span className="chat-citation-chip__title">{title}</span>
              </button>
            </Tooltip>
          );
        })}
      </div>

      <Modal
        open={!!preview}
        title={
          preview ? (
            <span>
              <FileTextOutlined style={{ marginRight: 8 }} />
              {preview.title || preview.name || "来源详情"}
            </span>
          ) : null
        }
        footer={null}
        onCancel={() => setPreview(null)}
        width={640}
      >
        {preview ? (
          <div>
            <div style={{ marginBottom: 12 }}>
              {preview.document_id != null && (
                <Tag color="blue">document_id: {preview.document_id}</Tag>
              )}
              {preview.score != null && (
                <Tag color="green">相似度: {Number(preview.score).toFixed(3)}</Tag>
              )}
              {preview.url && (
                <a href={preview.url} target="_blank" rel="noopener noreferrer">
                  <LinkOutlined /> 打开原链接
                </a>
              )}
            </div>
            {preview.snippet || preview.content ? (
              <div className="chat-citations__snippet">
                {preview.snippet || preview.content}
              </div>
            ) : (
              <Empty description="该来源没有可预览的片段" />
            )}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
