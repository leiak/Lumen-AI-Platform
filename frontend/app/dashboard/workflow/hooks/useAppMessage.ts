"use client";

import { App } from "antd";

/**
 * M30b: thin wrapper around App.useApp() that bundles the standard
 * error-detail extraction (mirrors the inline pattern used in the
 * pre-refactor page.tsx and other dashboard pages).
 *
 * Use this instead of `import { message } from "antd"` in workflow
 * list components — the static import doesn't render under antd v5 +
 * Next.js 15 strict mode (see MEMORY.md).
 */
export function extractErrorDetail(error: any, fallback: string): string {
  const detail =
    error?.response?.data?.detail ||
    error?.message ||
    fallback;
  return typeof detail === "string" ? detail : JSON.stringify(detail);
}

export function useAppMessage() {
  const { message, notification } = App.useApp();
  return { message, notification, extractErrorDetail };
}
