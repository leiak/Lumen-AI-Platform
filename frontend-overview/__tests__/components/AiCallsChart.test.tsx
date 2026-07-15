// frontend-overview/__tests__/components/AiCallsChart.test.tsx
// Verifies loading/error/success states + the range→granularity derivation
// (1h→minute, 30d→day, else→hour) that drives the second fetcher arg.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { AiCallsChart } from "@/components/overview/AiCallsChart";
import { useScreenStore } from "@/store/screen";

vi.mock("@/services/screen", () => ({
  screenApi: { getAiCalls: vi.fn() },
}));
import { screenApi } from "@/services/screen";

// Stub chart components so jsdom doesn't try to render canvas/SVG, and we
// can assert the data shape that flows into each chart.
vi.mock("@ant-design/charts", () => ({
  Line: (props: { data: unknown[] }) => (
    <div data-testid="line-chart" data-rows={JSON.stringify(props.data)} />
  ),
  Column: (props: { data: unknown[] }) => (
    <div data-testid="column-chart" data-rows={JSON.stringify(props.data)} />
  ),
}));

const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{children}</ConfigProvider>
);

const sampleData = {
  series: [
    { ts: "2026-06-05T10:00:00Z", calls: 100, errors: 3, avg_latency_ms: 250, p95_latency_ms: 800 },
    { ts: "2026-06-05T11:00:00Z", calls: 120, errors: 5, avg_latency_ms: 280, p95_latency_ms: 900 },
  ],
  by_model: [
    { model: "glm-4", calls: 150, errors: 4, avg_latency_ms: 260 },
    { model: "ollama", calls: 70, errors: 4, avg_latency_ms: 240 },
  ],
};

describe("AiCallsChart", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset store to the default range so derivation tests are isolated.
    useScreenStore.setState({ range: "24h" });
  });

  it("shows loading first", () => {
    (screenApi.getAiCalls as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise(() => {}),
    );
    render(<AiCallsChart />, { wrapper: TestWrapper });
    expect(document.querySelector(".ant-spin")).toBeTruthy();
  });

  it("shows error UI on failure", async () => {
    (screenApi.getAiCalls as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("net down"),
    );
    render(<AiCallsChart />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText(/net down/)).toBeInTheDocument();
    });
  });

  it("renders the two chart panels on success", async () => {
    (screenApi.getAiCalls as ReturnType<typeof vi.fn>).mockResolvedValue(sampleData);
    render(<AiCallsChart />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("AI 调用与错误数趋势")).toBeInTheDocument();
      expect(screen.getByText("按模型拆分")).toBeInTheDocument();
    });
    // Line chart receives the series exploded into 2 rows per timestamp
    // (one for `calls`, one for `errors`), so 2 series points → 4 rows.
    const lineChart = screen.getByTestId("line-chart");
    const lineRows = JSON.parse(lineChart.getAttribute("data-rows") || "[]");
    expect(lineRows).toHaveLength(4);
    expect(lineRows.filter((r: { metric: string }) => r.metric === "calls")).toHaveLength(2);
    expect(lineRows.filter((r: { metric: string }) => r.metric === "errors")).toHaveLength(2);
    // Column chart receives the by_model rows as-is.
    const colChart = screen.getByTestId("column-chart");
    const colRows = JSON.parse(colChart.getAttribute("data-rows") || "[]");
    expect(colRows).toHaveLength(2);
    expect(colRows[0]).toMatchObject({ model: "glm-4", calls: 150 });
  });

  it("derives granularity=hour from default range=24h", async () => {
    (screenApi.getAiCalls as ReturnType<typeof vi.fn>).mockResolvedValue(sampleData);
    render(<AiCallsChart />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screenApi.getAiCalls).toHaveBeenCalledWith("24h", "hour");
    });
  });

  it("derives granularity=minute when range=1h", async () => {
    useScreenStore.setState({ range: "1h" });
    (screenApi.getAiCalls as ReturnType<typeof vi.fn>).mockResolvedValue(sampleData);
    render(<AiCallsChart />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screenApi.getAiCalls).toHaveBeenCalledWith("1h", "minute");
    });
  });

  it("derives granularity=day when range=30d", async () => {
    useScreenStore.setState({ range: "30d" });
    (screenApi.getAiCalls as ReturnType<typeof vi.fn>).mockResolvedValue(sampleData);
    render(<AiCallsChart />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screenApi.getAiCalls).toHaveBeenCalledWith("30d", "day");
    });
  });
});
