"use client";
import { ConfigProvider, App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

export function TestWrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <ConfigProvider>
      <App>
        <QueryClientProvider client={qc}>
          {children}
        </QueryClientProvider>
      </App>
    </ConfigProvider>
  );
}
