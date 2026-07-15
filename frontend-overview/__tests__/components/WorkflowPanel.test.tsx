// frontend-overview/__tests__/components/WorkflowPanel.test.tsx
// Verifies loading/error/success states for the workflow/agent runs card.
// The Column chart is stubbed to a data-testid placeholder.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { WorkflowPanel } from "@/components/overview/WorkflowPanel";

vi.mock("@/services/screen", () => ({
  screenApi: { getWorkflows: vi.fn() },
}));
import { screenApi } from "@/services/screen";

vi.mock("@ant-design/charts", () => ({
  Column: (props: { data: unknown[] }) => (
    <div data-testid="column-chart" data-rows={JSON.stringify(props.data)} />
  ),
}));

const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{children}</ConfigProvider>
);

const sampleData = {
  total_workflows: 12,
  total_runs: 480,
  success: 460,
  failed: 15,
  cancelled: 5,
  avg_duration_ms: 2350,
  by_node_type: [
    { node_type: "llm", runs: 320, errors: 10 },
    { node_type: "condition", runs: 100, errors: 3 },
    { node_type: "code", runs: 60, errors: 2 },
  ],
};

describe("WorkflowPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows loading first", () => {
    (screenApi.getWorkflows as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise(() => {}),
    );
    render(<WorkflowPanel />, { wrapper: TestWrapper });
    expect(document.querySelector(".ant-spin")).toBeTruthy();
  });

  it("shows error UI on failure", async () => {
    (screenApi.getWorkflows as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("wf fetch failed"),
    );
    render(<WorkflowPanel />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText(/wf fetch failed/)).toBeInTheDocument();
    });
  });

  it("renders the workflow summary card on success", async () => {
    (screenApi.getWorkflows as ReturnType<typeof vi.fn>).mockResolvedValue(sampleData);
    render(<WorkflowPanel />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("工作流 / Agent 运行")).toBeInTheDocument();
    });
    // Top stats row: workflows / runs / avg duration.
    expect(screen.getByText(/工作流: 12/)).toBeInTheDocument();
    expect(screen.getByText(/运行: 480/)).toBeInTheDocument();
    expect(screen.getByText(/平均耗时 2350 ms/)).toBeInTheDocument();
    // Outcome row: success / failed / cancelled.
    expect(screen.getByText(/成功: 460/)).toBeInTheDocument();
    expect(screen.getByText(/失败: 15/)).toBeInTheDocument();
    expect(screen.getByText(/取消: 5/)).toBeInTheDocument();
  });

  it("passes by_node_type rows to the Column chart", async () => {
    (screenApi.getWorkflows as ReturnType<typeof vi.fn>).mockResolvedValue(sampleData);
    render(<WorkflowPanel />, { wrapper: TestWrapper });
    await waitFor(() => {
      const col = screen.getByTestId("column-chart");
      const rows = JSON.parse(col.getAttribute("data-rows") || "[]");
      expect(rows).toHaveLength(3);
      expect(rows[0]).toMatchObject({ type: "llm", runs: 320, errors: 10 });
    });
  });
});
