// frontend/__tests__/export-markdown.test.ts
//
// Tests for the markdown export utility. We mock the shared
// ``downloadBuffer`` helper and verify:
//   1. UTF-8 bytes are produced from the input text
//   2. The correct MIME type and Electron filters are passed
//   3. CJK characters survive the encode round-trip

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const downloadBufferMock = vi.fn();
vi.mock("@/lib/download-buffer", () => ({
  downloadBuffer: (...args: unknown[]) => downloadBufferMock(...args),
}));

import { downloadMarkdown } from "@/lib/export-markdown";

describe("downloadMarkdown", () => {
  beforeEach(() => {
    downloadBufferMock.mockReset();
    downloadBufferMock.mockResolvedValue({ delivered: true });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("encodes text as UTF-8 and forwards to downloadBuffer", async () => {
    await downloadMarkdown("# Hello", "chat.md");

    expect(downloadBufferMock).toHaveBeenCalledTimes(1);
    const arg = downloadBufferMock.mock.calls[0][0];
    expect(arg.filename).toBe("chat.md");
    expect(arg.mimeType).toBe("text/markdown;charset=utf-8");
    expect(arg.electronFilters).toEqual([
      { name: "Markdown 文档", extensions: ["md"] },
    ]);
    // The buffer must contain the ASCII bytes verbatim.
    const bytes = Array.from(arg.buffer as Uint8Array);
    const decoded = new TextDecoder().decode(new Uint8Array(bytes));
    expect(decoded).toBe("# Hello");
  });

  it("preserves Chinese characters (UTF-8 multi-byte)", async () => {
    const text = "# 中文标题\n\n内容";
    await downloadMarkdown(text, "chat.md");

    const arg = downloadBufferMock.mock.calls[0][0];
    const bytes = arg.buffer as Uint8Array;
    // UTF-8 of "中文标题" → 12 bytes (3 bytes per CJK char × 4).
    // Just sanity-check it's larger than the raw char count.
    expect(bytes.length).toBeGreaterThan(text.length);
    // Round-trip should be lossless.
    const decoded = new TextDecoder().decode(bytes);
    expect(decoded).toBe(text);
  });

  it("returns delivered=true on success", async () => {
    downloadBufferMock.mockResolvedValueOnce({ delivered: true });
    const result = await downloadMarkdown("# x", "x.md");
    expect(result).toEqual({ delivered: true });
  });

  it("forwards error messages from downloadBuffer", async () => {
    downloadBufferMock.mockResolvedValueOnce({
      delivered: false,
      error: "user cancelled",
    });
    const result = await downloadMarkdown("# x", "x.md");
    expect(result.delivered).toBe(false);
    expect(result.error).toBe("user cancelled");
  });
});