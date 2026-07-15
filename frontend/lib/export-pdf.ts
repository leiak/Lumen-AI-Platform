// frontend/lib/export-pdf.ts
//
// Export the chat message as PDF by POSTing the raw markdown to the
// backend ``/api/v1/export/pdf`` endpoint, which runs it through
// Playwright + Chromium to produce a print-quality PDF.
//
// We send the markdown as-is (no client-side pre-processing) so the
// server-side renderer is the single source of truth for the PDF
// layout — the chat UI and the exported PDF can drift apart in
// theory but match in practice.

import { downloadBuffer } from "./download-buffer";

export interface PdfExportOptions {
  /** Raw markdown from the chat message. */
  text: string;
  /** Filename the user sees in the save dialog / download bar. */
  filename: string;
  /** Document title for the PDF metadata; falls back to "Chat Export". */
  title?: string;
  /** Bearer token used for the backend call. Pass `""` to skip
   *  the Authorization header (only acceptable in test fixtures). */
  token: string;
  /** API base URL; defaults to NEXT_PUBLIC_API_URL at runtime. */
  apiBase?: string;
}

export async function downloadPdfFromBackend(
  opts: PdfExportOptions,
): Promise<{ delivered: boolean; error?: string }> {
  const apiBase =
    opts.apiBase ??
    (typeof process !== "undefined"
      ? process.env.NEXT_PUBLIC_API_URL
      : undefined) ??
    "http://localhost:11335/api/v1";

  let pdfBytes: Uint8Array;
  try {
    const response = await fetch(`${apiBase}/export/pdf`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(opts.token ? { Authorization: `Bearer ${opts.token}` } : {}),
      },
      body: JSON.stringify({
        markdown: opts.text,
        title: opts.title ?? "Chat Export",
      }),
    });
    if (!response.ok) {
      // Surface the server's structured error if any, otherwise a
      // generic status-text message.
      const detail = await response.text();
      let msg: string;
      try {
        const parsed = JSON.parse(detail);
        msg = parsed.detail ?? detail;
      } catch {
        msg = detail || response.statusText;
      }
      return { delivered: false, error: `HTTP ${response.status}: ${msg}` };
    }
    pdfBytes = new Uint8Array(await response.arrayBuffer());
  } catch (e) {
    return {
      delivered: false,
      error: e instanceof Error ? e.message : String(e),
    };
  }

  return downloadBuffer({
    buffer: pdfBytes,
    filename: opts.filename,
    mimeType: "application/pdf",
    electronFilters: [
      { name: "PDF 文档", extensions: ["pdf"] },
    ],
  });
}