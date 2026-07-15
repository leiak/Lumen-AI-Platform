"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { CodeBlock, InlineCode } from "./CodeBlock";
import type { Components } from "react-markdown";

interface MarkdownProps {
  content: string;
}

/**
 * Render assistant content as Markdown.
 * - GitHub-flavored Markdown via remark-gfm (tables, task lists, strikethrough, autolinks)
 * - Syntax highlighting via rehype-highlight
 * - Custom code-block renderer with language label and copy-to-clipboard
 *
 * Streaming: react-markdown re-parses on every render; partial Markdown
 * (e.g. an unclosed code fence) is handled gracefully — the parser simply
 * leaves the incomplete block as inline text until the next chunk arrives.
 */
export function Markdown({ content }: MarkdownProps) {
  const components: Components = {
    code({ inline, className, children, ...rest }: any) {
      if (inline) {
        return <InlineCode>{children}</InlineCode>;
      }
      // Block code (with or without a language tag)
      return <CodeBlock className={className}>{children}</CodeBlock>;
    },
    a({ children, href, ...rest }: any) {
      const safeHref = typeof href === "string" ? href : "#";
      const isExternal = /^https?:\/\//i.test(safeHref);
      return (
        <a
          href={safeHref}
          target={isExternal ? "_blank" : undefined}
          rel={isExternal ? "noopener noreferrer" : undefined}
          className="chat-md-link"
          {...rest}
        >
          {children}
        </a>
      );
    },
    table({ children, ...rest }: any) {
      return (
        <div className="chat-md-table-wrap">
          <table className="chat-md-table" {...rest}>
            {children}
          </table>
        </div>
      );
    },
  };

  return (
    <div className="chat-md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={components}
      >
        {content || ""}
      </ReactMarkdown>
    </div>
  );
}
