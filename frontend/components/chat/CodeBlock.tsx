"use client";

import { useState, ReactNode } from "react";
import { Tooltip } from "antd";
import { CopyOutlined, CheckOutlined } from "@ant-design/icons";

interface CodeBlockProps {
  className?: string;
  children?: ReactNode;
  inline?: boolean;
}

const LANGUAGE_RE = /language-([\w-]+)/;

/**
 * Custom code block renderer used by the Markdown component.
 * - Shows a language label
 * - Renders a copy-to-clipboard button
 * - Preserves indentation and horizontal scrolling
 */
export function CodeBlock({ className, children }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const match = LANGUAGE_RE.exec(className || "");
  const language = match ? match[1] : "";
  const raw = stringifyChildren(children);

  const handleCopy = async () => {
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(raw);
      } else if (typeof document !== "undefined") {
        // Fallback for older browsers
        const ta = document.createElement("textarea");
        ta.value = raw;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (e) {
      // Silently fail; UI shows nothing on copy failure.
      if (process.env.NODE_ENV === "development") {
        console.error("Copy failed:", e);
      }
    }
  };

  return (
    <div className="chat-codeblock">
      <div className="chat-codeblock__header">
        <span className="chat-codeblock__lang">{language || "text"}</span>
        <Tooltip title={copied ? "已复制" : "复制代码"}>
          <button
            type="button"
            className="chat-codeblock__copy"
            onClick={handleCopy}
            aria-label="复制代码"
          >
            {copied ? <CheckOutlined /> : <CopyOutlined />}
            <span style={{ marginLeft: 4 }}>{copied ? "已复制" : "复制"}</span>
          </button>
        </Tooltip>
      </div>
      <pre className="chat-codeblock__pre">
        <code className={className}>{children}</code>
      </pre>
    </div>
  );
}

/**
 * Inline code renderer. Plain pill, no header/copy button.
 */
export function InlineCode({ children }: { children?: ReactNode }) {
  return <code className="chat-inline-code">{children}</code>;
}

function stringifyChildren(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(stringifyChildren).join("");
  if (typeof node === "object" && "props" in node) {
    const props = (node as { props: { children?: ReactNode } }).props;
    return stringifyChildren(props.children);
  }
  return "";
}
