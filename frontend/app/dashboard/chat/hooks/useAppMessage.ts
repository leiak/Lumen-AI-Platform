"use client";

import { App } from "antd";

/**
 * M30b-style: thin wrapper around App.useApp() that bundles the standard
 * error-detail extraction. Mirrors ``frontend/app/dashboard/workflow/hooks/useAppMessage.ts``
 * (identical API);复制而非 cross-folder 引用,避免 chat 模块对 workflow 模块
 * 形成隐式依赖。
 *
 * Use this instead of `import { message } from "antd"` — the static import
 * doesn't render under antd v5 + Next.js 15 strict mode (MEMORY.md).
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