// frontend/__tests__/download-buffer.test.ts
//
// Regression coverage for the buffer-to-Blob dispatch in the browser
// download path. Two things must hold:
//
// 1. The synthetic ``<a download>`` element uses the right filename
//    and ``href``.
//
// 2. The Blob handed to ``URL.createObjectURL`` contains the ORIGINAL
//    raw bytes, not a UTF-8-encoded stringification of the buffer.
//
// Item 2 is the bug the user hit: passing a plain ``number[]`` to
// the Blob constructor makes the spec fall back to
// ``String(part)`` which is ``Array.prototype.toString`` for arrays —
// i.e. ``"229,133,177,232,..."`` — and then that comma-joined string
// is what lands on disk. .md files end up as lines of digits; .pdf
// files become unopenable garbage because the actual %PDF- bytes
// were never written.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { downloadBuffer } from "@/lib/download-buffer";

describe("downloadBuffer (browser path)", () => {
  let createObjectURLSpy: ReturnType<typeof vi.fn>;
  let revokeObjectURLSpy: ReturnType<typeof vi.fn>;
  let clickSpy: ReturnType<typeof vi.fn>;
  // We spy on the Blob constructor itself so we can read the parts
  // directly — jsdom's Blob polyfill doesn't expose .arrayBuffer()
  // or .text(), so the only reliable way to assert "raw bytes went
  // in" is to capture the constructor arguments.
  let blobCtorSpy: ReturnType<typeof vi.fn>;
  let lastBlobParts: BlobPart[] | undefined;
  let lastBlobOptions: BlobPropertyBag | undefined;

  beforeEach(() => {
    lastBlobParts = undefined;
    lastBlobOptions = undefined;
    // Capture the real Blob constructor BEFORE we stub the global
    // — the spy must hand back a genuine Blob so downstream code
    // (URL.createObjectURL, FileReader, etc.) keeps working.
    const RealBlob = (globalThis as unknown as {
      Blob: new (p: BlobPart[], o?: BlobPropertyBag) => Blob;
    }).Blob;

    blobCtorSpy = vi.fn((parts: BlobPart[], options?: BlobPropertyBag) => {
      lastBlobParts = parts;
      lastBlobOptions = options;
      return new RealBlob(parts, options);
    });

    createObjectURLSpy = vi.fn(() => "blob:mock-url");
    revokeObjectURLSpy = vi.fn();
    clickSpy = vi.fn();

    vi.stubGlobal("Blob", blobCtorSpy);
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: createObjectURLSpy,
      revokeObjectURL: revokeObjectURLSpy,
    });

    const origCreate = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation(((tag: string) => {
      const el = origCreate(tag);
      if (tag === "a") {
        (el as HTMLAnchorElement).click = clickSpy;
      }
      return el;
    }) as typeof document.createElement);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("writes the raw UTF-8 bytes for a markdown payload", async () => {
    const text = "你好 world";
    const u8 = new TextEncoder().encode(text);
    await downloadBuffer({
      buffer: u8,
      filename: "chat.md",
      mimeType: "text/markdown;charset=utf-8",
      electronFilters: [{ name: "Markdown 文档", extensions: ["md"] }],
    });

    expect(blobCtorSpy).toHaveBeenCalledTimes(1);
    expect(lastBlobOptions?.type).toBe("text/markdown;charset=utf-8");
    expect(lastBlobParts).toBeDefined();
    expect(lastBlobParts!.length).toBe(1);
    // The single part MUST be a Uint8Array (BufferSource), not a
    // comma-joined string. If the bug regresses, the parts would
    // be the string "228,184,170,...", which fails the type check.
    const part = lastBlobParts![0];
    expect(part).toBeInstanceOf(Uint8Array);
    expect((part as Uint8Array).byteLength).toBe(u8.byteLength);
    expect(Array.from(part as Uint8Array)).toEqual(Array.from(u8));
  });

  it("writes raw PDF bytes (not a digit string) to the Blob", async () => {
    const pdfBytes = new Uint8Array([
      0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x34, // %PDF-1.4
      0x00, 0xff, 0x12, 0x34,
    ]);
    await downloadBuffer({
      buffer: pdfBytes,
      filename: "out.pdf",
      mimeType: "application/pdf",
      electronFilters: [{ name: "PDF 文档", extensions: ["pdf"] }],
    });

    expect(lastBlobParts).toBeDefined();
    const part = lastBlobParts![0];
    // The Blob part must be the original Uint8Array, not a string
    // representation of the array (which would be the regression
    // symptom: a comma-joined ASCII digit string in the file).
    expect(part).toBeInstanceOf(Uint8Array);
    const bytes = part as Uint8Array;
    expect(bytes.byteLength).toBe(pdfBytes.byteLength);
    expect(bytes[0]).toBe(0x25); // '%'
    expect(bytes[1]).toBe(0x50); // 'P'
    expect(bytes[2]).toBe(0x44); // 'D'
    expect(bytes[3]).toBe(0x46); // 'F'
  });

  it("attaches the filename to the synthetic <a download> and clicks it", async () => {
    await downloadBuffer({
      buffer: new Uint8Array([1, 2, 3]),
      filename: "report-2026.pdf",
      mimeType: "application/pdf",
      electronFilters: [{ name: "PDF", extensions: ["pdf"] }],
    });
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(createObjectURLSpy).toHaveBeenCalledTimes(1);
  });

  it("revokes the object URL after a delay", async () => {
    vi.useFakeTimers();
    try {
      await downloadBuffer({
        buffer: new Uint8Array([1, 2, 3]),
        filename: "x.md",
        mimeType: "text/markdown",
        electronFilters: [{ name: "MD", extensions: ["md"] }],
      });
      expect(revokeObjectURLSpy).not.toHaveBeenCalled();
      vi.advanceTimersByTime(1100);
      expect(revokeObjectURLSpy).toHaveBeenCalledWith("blob:mock-url");
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("downloadBuffer (Electron path)", () => {
  const electronSave = vi.fn();

  beforeEach(() => {
    electronSave.mockReset();
    electronSave.mockResolvedValue({ ok: true, path: "/tmp/x.pdf" });
    (window as unknown as { electronAPI?: { saveFile: typeof electronSave } })
      .electronAPI = { saveFile: electronSave };
  });

  afterEach(() => {
    delete (window as unknown as { electronAPI?: unknown }).electronAPI;
  });

  it("sends a number[] over IPC (stable across Electron versions)", async () => {
    const bytes = new Uint8Array([10, 20, 30, 40]);
    const result = await downloadBuffer({
      buffer: bytes,
      filename: "x.pdf",
      mimeType: "application/pdf",
      electronFilters: [{ name: "PDF", extensions: ["pdf"] }],
    });
    expect(result).toEqual({ delivered: true, path: "/tmp/x.pdf" });
    expect(electronSave).toHaveBeenCalledTimes(1);
    const arg = electronSave.mock.calls[0][0];
    // Must be a plain number[] — Electron's structured-clone is
    // finicky across versions for typed arrays / ArrayBuffer.
    expect(Array.isArray(arg.buffer)).toBe(true);
    expect(arg.buffer).toEqual([10, 20, 30, 40]);
  });

  it("forwards cancellation as delivered=false", async () => {
    electronSave.mockResolvedValueOnce({ ok: false, canceled: true });
    const result = await downloadBuffer({
      buffer: new Uint8Array([1]),
      filename: "x.md",
      mimeType: "text/markdown",
      electronFilters: [],
    });
    expect(result).toEqual({ delivered: false });
  });

  it("forwards error as delivered=false + error string", async () => {
    electronSave.mockResolvedValueOnce({ ok: false, error: "EACCES" });
    const result = await downloadBuffer({
      buffer: new Uint8Array([1]),
      filename: "x.md",
      mimeType: "text/markdown",
      electronFilters: [],
    });
    expect(result).toEqual({ delivered: false, error: "EACCES" });
  });
});