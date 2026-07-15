// frontend/__tests__/export-pdf.test.ts
//
// Tests for the PDF export utility. We stub global.fetch and mock
// the shared ``downloadBuffer`` helper, then verify:
//   1. POST goes to /api/v1/export/pdf with the right headers + body
//   2. Bearer token is forwarded from the ``token`` option
//   3. Successful response bytes flow into downloadBuffer with the
//      correct mime + filters
//   4. Non-2xx responses surface their ``detail`` payload as an error
//   5. Network errors are caught and surfaced as error messages

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const downloadBufferMock = vi.fn();
vi.mock("@/lib/download-buffer", () => ({
  downloadBuffer: (...args: unknown[]) => downloadBufferMock(...args),
}));

import { downloadPdfFromBackend } from "@/lib/export-pdf";

const PDF_BYTES = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x34]); // %PDF-1.4

function mockFetchResponse(init: {
  ok: boolean;
  status?: number;
  body?: ArrayBuffer;
  textBody?: string;
}) {
  const fetchMock = vi.fn().mockResolvedValueOnce({
    ok: init.ok,
    status: init.status ?? (init.ok ? 200 : 500),
    statusText: init.ok ? "OK" : "Server Error",
    text: async () => init.textBody ?? "",
    arrayBuffer: async () => init.body ?? new ArrayBuffer(0),
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("downloadPdfFromBackend", () => {
  beforeEach(() => {
    downloadBufferMock.mockReset();
    downloadBufferMock.mockResolvedValue({ delivered: true });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("POSTs to /api/v1/export/pdf with the markdown payload + bearer token", async () => {
    const fetchMock = mockFetchResponse({
      ok: true,
      body: PDF_BYTES.buffer.slice(
        PDF_BYTES.byteOffset,
        PDF_BYTES.byteOffset + PDF_BYTES.byteLength,
      ),
    });

    await downloadPdfFromBackend({
      text: "# 你好",
      filename: "out.pdf",
      token: "tk-123",
      apiBase: "http://api.example/api/v1",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.example/api/v1/export/pdf");
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(init.headers.Authorization).toBe("Bearer tk-123");
    expect(JSON.parse(init.body)).toEqual({
      markdown: "# 你好",
      title: "Chat Export",
    });
  });

  it("omits Authorization header when token is empty", async () => {
    const fetchMock = mockFetchResponse({
      ok: true,
      body: PDF_BYTES.buffer.slice(
        PDF_BYTES.byteOffset,
        PDF_BYTES.byteOffset + PDF_BYTES.byteLength,
      ),
    });

    await downloadPdfFromBackend({
      text: "x",
      filename: "out.pdf",
      token: "",
      apiBase: "http://api.example/api/v1",
    });

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers.Authorization).toBeUndefined();
  });

  it("uses a custom title when supplied", async () => {
    const fetchMock = mockFetchResponse({
      ok: true,
      body: PDF_BYTES.buffer.slice(
        PDF_BYTES.byteOffset,
        PDF_BYTES.byteOffset + PDF_BYTES.byteLength,
      ),
    });

    await downloadPdfFromBackend({
      text: "x",
      filename: "out.pdf",
      token: "t",
      title: "Custom Title",
      apiBase: "http://api.example/api/v1",
    });

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body).title).toBe("Custom Title");
  });

  it("forwards the PDF bytes to downloadBuffer with the right mime + filters", async () => {
    mockFetchResponse({
      ok: true,
      body: PDF_BYTES.buffer.slice(
        PDF_BYTES.byteOffset,
        PDF_BYTES.byteOffset + PDF_BYTES.byteLength,
      ),
    });

    const result = await downloadPdfFromBackend({
      text: "x",
      filename: "out.pdf",
      token: "t",
      apiBase: "http://api.example/api/v1",
    });
    expect(result).toEqual({ delivered: true });
    expect(downloadBufferMock).toHaveBeenCalledTimes(1);
    const arg = downloadBufferMock.mock.calls[0][0];
    expect(arg.filename).toBe("out.pdf");
    expect(arg.mimeType).toBe("application/pdf");
    expect(arg.electronFilters).toEqual([
      { name: "PDF 文档", extensions: ["pdf"] },
    ]);
    // Bytes must start with the PDF magic.
    const bytes = arg.buffer as Uint8Array;
    expect(Array.from(bytes.slice(0, 5))).toEqual([0x25, 0x50, 0x44, 0x46, 0x2d]);
  });

  it("surfaces server error detail on non-2xx responses", async () => {
    mockFetchResponse({
      ok: false,
      status: 413,
      textBody: JSON.stringify({ detail: "markdown payload too large" }),
    });

    const result = await downloadPdfFromBackend({
      text: "x",
      filename: "out.pdf",
      token: "t",
      apiBase: "http://api.example/api/v1",
    });
    expect(result.delivered).toBe(false);
    expect(result.error).toContain("HTTP 413");
    expect(result.error).toContain("markdown payload too large");
    // downloadBuffer should NOT be called when the fetch fails —
    // there's nothing to save.
    expect(downloadBufferMock).not.toHaveBeenCalled();
  });

  it("surfaces network errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValueOnce(new Error("network down")),
    );

    const result = await downloadPdfFromBackend({
      text: "x",
      filename: "out.pdf",
      token: "t",
      apiBase: "http://api.example/api/v1",
    });
    expect(result.delivered).toBe(false);
    expect(result.error).toBe("network down");
    expect(downloadBufferMock).not.toHaveBeenCalled();
  });
});