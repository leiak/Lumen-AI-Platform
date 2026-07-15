// frontend/lib/download-buffer.ts
//
// Shared buffer-download helper used by every chat export format
// (Word / PDF / Markdown).
//
// Two delivery paths, picked at runtime:
//
// - Electron desktop: ``window.electronAPI.saveFile`` opens the
//   platform-native save dialog and writes the buffer straight to
//   the chosen path. Returns ``{ok, path}`` / ``{canceled}`` /
//   ``{error}``.
//
// - Plain browser: build a ``Blob`` URL, attach to a synthetic
//   ``<a download>``, click, then revoke the URL after a short
//   delay so the browser has time to start the download.
//
// We pass the buffer as ``number[]`` over the Electron IPC channel
// because Uint8Array structured-clone behaves differently across
// Electron versions; number[] is the boring stable encoding.

export interface ElectronSaveResult {
  ok: boolean;
  path?: string;
  canceled?: boolean;
  error?: string;
}

export interface ElectronSaveAPI {
  (opts: {
    defaultName: string;
    filters: Array<{ name: string; extensions: string[] }>;
    buffer: number[];
  }): Promise<ElectronSaveResult>;
}

export function getElectronSave(): ElectronSaveAPI | undefined {
  if (typeof window === "undefined") return undefined;
  const api = (window as unknown as {
    electronAPI?: { saveFile?: ElectronSaveAPI };
  }).electronAPI;
  return api?.saveFile;
}

export interface DownloadBufferOptions {
  /** The binary content to write. May be Uint8Array or plain number[]. */
  buffer: Uint8Array | number[];
  /** Filename the user sees in the save dialog / download bar. */
  filename: string;
  /** MIME type used for the Blob fallback path. */
  mimeType: string;
  /** Electron save-dialog file filters (extension list). */
  electronFilters: Array<{ name: string; extensions: string[] }>;
}

/** Dispatch a buffer to the right download path. */
export async function downloadBuffer(opts: DownloadBufferOptions): Promise<{
  /** True if the file was saved / downloaded; false if the user cancelled. */
  delivered: boolean;
  /** Electron-only: the absolute path the file was written to. */
  path?: string;
  /** Error message on failure; undefined on success. */
  error?: string;
}> {
  // Normalise to Uint8Array once. Used for both the browser Blob
  // (which wants a real BufferSource) and as the source for the
  // number[] that goes over Electron's IPC channel.
  const u8 =
    opts.buffer instanceof Uint8Array
      ? opts.buffer
      : new Uint8Array(opts.buffer);

  const electronSave = getElectronSave();
  if (typeof electronSave === "function") {
    // number[] over IPC: structured-clone handles plain number
    // arrays identically across Electron versions, whereas typed
    // arrays and ArrayBuffers have shipped subtle compat bugs
    // between Electron 12 and 22.
    const result = await electronSave({
      defaultName: opts.filename,
      filters: opts.electronFilters,
      buffer: Array.from(u8),
    });
    if (result.ok) {
      return { delivered: true, path: result.path };
    }
    if ("canceled" in result) {
      return { delivered: false };
    }
    return { delivered: false, error: result.error };
  }

  // Browser fallback: Blob + object URL + synthetic <a download>.
  //
  // The Blob constructor's BlobPart list accepts BufferSource
  // (ArrayBuffer / typed array / DataView), Blob, or string — but
  // NOT a plain ``number[]``. If you pass one, the spec falls back
  // to ``String(part)`` which for arrays means
  // ``Array.prototype.toString()``, i.e. comma-joined decimals:
  // ``"229,133,177,232,174,161"``. That string then gets encoded
  // as UTF-8 and ends up in the .md file as literal digits, while
  // the .pdf case produces a non-PDF file that editors refuse to
  // open. The fix is to hand the Blob the original Uint8Array.
  const blob = new Blob([u8], { type: opts.mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = opts.filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Defer revoke so the browser has a chance to start the download;
  // revoking too early produces a phantom file the user can't open.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return { delivered: true };
}