// frontend/__tests__/external-apps/list.test.tsx
// Render-level test for /dashboard/external-apps list page.
//
// Mocks the `externalAppApi.list` (the service's flat shape
// {items, total, page, page_size}, NOT the backend envelope — the
// service does the unwrap in Task 18) and verifies the table renders
// a row, the page heading, and the rate column.
//
// IMPORTANT: the page uses `App.useApp()` for toasts (per MEMORY.md
// pitfall — static `import { message }` doesn't render under
// Next.js 15 App Router + React strict mode). The test must wrap the
// page in antd's `<App>` so `App.useApp()` doesn't throw.
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { App as AntdApp } from "antd";

// The page uses next/navigation's useRouter (to navigate to the
// "new" page). jsdom doesn't provide a Next router, so mount a stub.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => "/dashboard/external-apps",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/services/externalApp", () => ({
  externalAppApi: {
    list: vi.fn().mockResolvedValue({
      items: [
        {
          id: 1,
          name: "shop",
          app_key: "lc_pub_xxxxxxxxxxxxxxxx",
          is_active: true,
          allowed_origins: ["https://shop.example.com"],
          allowed_agent_ids: [],
          allowed_team_ids: [],
          rate_limit_per_min: 60,
          scopes: "chat:stream",
          tenant_id: 1,
          description: null,
          created_by: null,
          last_used_at: null,
          created_at: "",
          updated_at: "",
          allowed_agent_names: ["support"],
          allowed_team_names: [],
        },
      ],
      total: 1,
      page: 1,
      page_size: 20,
    }),
  },
}));

import ExternalAppsPage from "@/app/dashboard/external-apps/page";

describe("ExternalAppsPage", () => {
  it("renders the list", async () => {
    render(
      <AntdApp>
        <ExternalAppsPage />
      </AntdApp>
    );
    await waitFor(() => expect(screen.getByText("shop")).toBeInTheDocument());
    expect(screen.getByText("外部应用授权")).toBeInTheDocument();
    expect(screen.getByText("60/min")).toBeInTheDocument();
  });
});
