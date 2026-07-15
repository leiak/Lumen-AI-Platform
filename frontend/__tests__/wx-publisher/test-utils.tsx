// frontend/__tests__/wx-publisher/test-utils.tsx
// M32 — 公众号助手 — shared test wrapper.
//
// Mirrors the pattern from __tests__/image-generation/test-utils.tsx:
// ConfigProvider + App (App.useApp() needs the App context for toast to
// render in jsdom) + QueryClientProvider.
"use client";
import { ConfigProvider, App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

export function TestWrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <ConfigProvider>
      <App>
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      </App>
    </ConfigProvider>
  );
}