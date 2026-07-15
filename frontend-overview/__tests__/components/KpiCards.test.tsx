import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { KpiCards } from "@/components/overview/KpiCards";

vi.mock("@/services/screen", () => ({
  screenApi: { getOverview: vi.fn() },
}));
import { screenApi } from "@/services/screen";

const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{children}</ConfigProvider>
);

describe("KpiCards", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows loading first", () => {
    (screenApi.getOverview as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
    render(<KpiCards />, { wrapper: TestWrapper });
    expect(document.querySelector(".ant-spin")).toBeTruthy();
  });

  it("renders 6 KPI cards on success", async () => {
    (screenApi.getOverview as ReturnType<typeof vi.fn>).mockResolvedValue({
      range: "24h", total_tenants: 5, active_tenants: 3, total_users: 10, active_users: 4,
      total_agents: 7, total_kbs: 2, total_workflows: 4, total_documents: 20,
      total_chunks: 100, total_chat_messages: 200, ai_calls: 50, ai_errors: 2, ai_error_rate: 0.04,
      top_tenants: [], data_source_note: "x",
    });
    render(<KpiCards />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("租户数")).toBeInTheDocument();
      expect(screen.getByText("活跃租户")).toBeInTheDocument();
      expect(screen.getByText("用户数")).toBeInTheDocument();
      expect(screen.getByText("Agent 数")).toBeInTheDocument();
      expect(screen.getByText("工作流")).toBeInTheDocument();
      expect(screen.getByText("AI 调用 (24h)")).toBeInTheDocument();
    });
  });

  it("shows error UI on failure", async () => {
    (screenApi.getOverview as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("net"));
    render(<KpiCards />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText(/net/)).toBeInTheDocument();
    });
  });
});
