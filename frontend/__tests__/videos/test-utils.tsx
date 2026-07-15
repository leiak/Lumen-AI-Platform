// frontend/__tests__/videos/test-utils.tsx
// M36.1 — TestWrapper for /dashboard/videos tests.
//
// Mirrors __tests__/m35/test-utils.tsx — ConfigProvider + App + QueryClient.
// Needed because the videos page uses App.useApp() (toast per
// MEMORY 2026-06-07), react-query polling at 5s, and Modal/Form heavily.

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