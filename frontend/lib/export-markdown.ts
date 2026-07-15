// frontend/lib/export-markdown.ts
//
// Export the chat message as a plain ``.md`` file. This is the
// no-frills sibling of the Word / PDF exports — the LLM output is
// already markdown, so we just hand the raw text back to the user.
//
// UTF-8 is mandatory: chat content is mostly Chinese, so emitting
// latin-1 would corrupt every non-ASCII character on disk.

import { downloadBuffer } from "./download-buffer";

const MD_MIME = "text/markdown;charset=utf-8";

function utf8Bytes(text: string): Uint8Array {
  // TextEncoder is available in every supported browser + Node 18+
  // and always emits UTF-8, regardless of platform default encoding.
  return new TextEncoder().encode(text);
}

export async function downloadMarkdown(
  text: string,
  filename: string,
): Promise<{ delivered: boolean; error?: string }> {
  return downloadBuffer({
    buffer: utf8Bytes(text),
    filename,
    mimeType: MD_MIME,
    electronFilters: [
      { name: "Markdown 文档", extensions: ["md"] },
    ],
  });
}