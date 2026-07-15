// frontend/__tests__/m35/test-utils.tsx
// M35 — TTS / Subtitle / Playbook page tests
//
// Same pattern as __tests__/image-generation/test-utils.tsx but lives in the
// m35 subdir. Pages in this suite use `App.useApp()` (toast pattern per
// MEMORY 2026-06-07) AND `react-query` (useQuery polling at 2s intervals
// for TTS history). The TestWrapper must include all three:
import { ConfigProvider, App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

export function TestWrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <ConfigProvider button={{ autoInsertSpace: false }}>
      <App>
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      </App>
    </ConfigProvider>
  );
}
