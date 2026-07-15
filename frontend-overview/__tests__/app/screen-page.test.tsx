// frontend-overview/__tests__/app/screen-page.test.tsx
// Smoke test for the (screen)/page root: all 5 panels must mount and call
// their respective screenApi method on first render. The charts are stubbed
// because jsdom can't render canvas/SVG.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ConfigProvider } from "antd";
import ScreenPage from "@/app/(screen)/page";

vi.mock("@/services/screen", () => ({
  screenApi: {
    getOverview: vi.fn(),
    getAiCalls: vi.fn(),
    getKnowledge: vi.fn(),
    getWorkflows: vi.fn(),
    getTenantsUsers: vi.fn(),
  },
}));
import { screenApi } from "@/services/screen";

vi.mock("@ant-design/charts", () => ({
  Line: () => <div data-testid="chart-line" />,
  Column: () => <div data-testid="chart-column" />,
  Pie: () => <div data-testid="chart-pie" />,
}));

const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{children}</ConfigProvider>
);

const overview = {
  range: "24h", total_tenants: 1, active_tenants: 1, total_users: 2, active_users: 1,
  total_agents: 0, total_kbs: 0, total_workflows: 0, total_documents: 0,
  total_chunks: 0, total_chat_messages: 0, ai_calls: 0, ai_errors: 0, ai_error_rate: 0,
  top_tenants: [], data_source_note: "x",
};
const aiCalls = { series: [], by_model: [] };
const knowledge = { total_kbs: 0, total_documents: 0, total_chunks: 0,
  parse_success: 0, parse_failed: 0, embedding_failed: 0, by_status: [] };
const workflows = { total_workflows: 0, total_runs: 0, success: 0, failed: 0,
  cancelled: 0, avg_duration_ms: 0, by_node_type: [] };
const tenantsUsers = { tenant_growth: [], user_growth: [], top_active_tenants: [] };

describe("ScreenPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (screenApi.getOverview as ReturnType<typeof vi.fn>).mockResolvedValue(overview);
    (screenApi.getAiCalls as ReturnType<typeof vi.fn>).mockResolvedValue(aiCalls);
    (screenApi.getKnowledge as ReturnType<typeof vi.fn>).mockResolvedValue(knowledge);
    (screenApi.getWorkflows as ReturnType<typeof vi.fn>).mockResolvedValue(workflows);
    (screenApi.getTenantsUsers as ReturnType<typeof vi.fn>).mockResolvedValue(tenantsUsers);
  });

  it("renders all 5 panel titles", async () => {
    // Note: header is in the (screen) layout, not in the page — not asserted here.
    render(<ScreenPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("AI 调用与错误数趋势")).toBeInTheDocument();
      expect(screen.getByText("知识库 / 文档")).toBeInTheDocument();
      expect(screen.getByText("工作流 / Agent 运行")).toBeInTheDocument();
      expect(screen.getByText("租户 / 用户")).toBeInTheDocument();
    });
    // KPI cards render 6 labels, "租户数" is the first — sufficient to
    // assert the panel mounted without depending on CountUp animation.
    expect(screen.getByText("租户数")).toBeInTheDocument();
  });

  it("fans out to all 5 screenApi endpoints on mount", async () => {
    render(<ScreenPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screenApi.getOverview).toHaveBeenCalledTimes(1);
      expect(screenApi.getAiCalls).toHaveBeenCalledTimes(1);
      expect(screenApi.getKnowledge).toHaveBeenCalledTimes(1);
      expect(screenApi.getWorkflows).toHaveBeenCalledTimes(1);
      expect(screenApi.getTenantsUsers).toHaveBeenCalledTimes(1);
    });
  });
});
