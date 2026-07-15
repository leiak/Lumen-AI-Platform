// frontend-overview/__tests__/components/TenantUserPanel.test.tsx
// Verifies loading/error/success states for the tenant/user card.
// The Line chart is stubbed to a data-testid placeholder; the AntD List
// renders normally so we can assert List.Item content.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { TenantUserPanel } from "@/components/overview/TenantUserPanel";

vi.mock("@/services/screen", () => ({
  screenApi: { getTenantsUsers: vi.fn() },
}));
import { screenApi } from "@/services/screen";

vi.mock("@ant-design/charts", () => ({
  Line: (props: { data: unknown[] }) => (
    <div data-testid="line-chart" data-rows={JSON.stringify(props.data)} />
  ),
}));

const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{children}</ConfigProvider>
);

const sampleData = {
  tenant_growth: [
    { ts: "2026-06-04T00:00:00Z", count: 10 },
    { ts: "2026-06-05T00:00:00Z", count: 12 },
  ],
  user_growth: [
    { ts: "2026-06-04T00:00:00Z", count: 80 },
    { ts: "2026-06-05T00:00:00Z", count: 95 },
  ],
  top_active_tenants: [
    { tenant_id: 1, calls: 1500, messages: 300 },
    { tenant_id: 2, calls: 900, messages: 180 },
  ],
};

describe("TenantUserPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows loading first", () => {
    (screenApi.getTenantsUsers as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise(() => {}),
    );
    render(<TenantUserPanel />, { wrapper: TestWrapper });
    expect(document.querySelector(".ant-spin")).toBeTruthy();
  });

  it("shows error UI on failure", async () => {
    (screenApi.getTenantsUsers as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("tu fetch failed"),
    );
    render(<TenantUserPanel />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText(/tu fetch failed/)).toBeInTheDocument();
    });
  });

  it("renders the tenant/user card on success", async () => {
    (screenApi.getTenantsUsers as ReturnType<typeof vi.fn>).mockResolvedValue(sampleData);
    render(<TenantUserPanel />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("租户 / 用户")).toBeInTheDocument();
    });
    // Subtitle for the top-active-tenants list.
    expect(screen.getByText("Top 活跃租户")).toBeInTheDocument();
    // List items rendered as "Tenant#N · calls M".
    expect(screen.getByText(/Tenant#1 · calls 1500/)).toBeInTheDocument();
    expect(screen.getByText(/Tenant#2 · calls 900/)).toBeInTheDocument();
  });

  it("passes combined growth rows to the Line chart", async () => {
    (screenApi.getTenantsUsers as ReturnType<typeof vi.fn>).mockResolvedValue(sampleData);
    render(<TenantUserPanel />, { wrapper: TestWrapper });
    await waitFor(() => {
      const line = screen.getByTestId("line-chart");
      const rows = JSON.parse(line.getAttribute("data-rows") || "[]");
      // tenant_growth (2) + user_growth (2) → 4 rows tagged by metric.
      expect(rows).toHaveLength(4);
      expect(rows.filter((r: { metric: string }) => r.metric === "tenants")).toHaveLength(2);
      expect(rows.filter((r: { metric: string }) => r.metric === "users")).toHaveLength(2);
    });
  });
});
