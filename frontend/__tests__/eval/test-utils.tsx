// frontend/__tests__/eval/test-utils.tsx
// M37.1 — TestWrapper for /dashboard/eval/datasets tests.
//
// 跟 videos/m35 一致:ConfigProvider + App + QueryClient。

import { ConfigProvider, App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

export function TestWrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <ConfigProvider button={{ autoInsertSpace: false }}>
      <App>
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      </App>
    </ConfigProvider>
  );
}