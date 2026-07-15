// frontend-overview/__tests__/components/KnowledgePanel.test.tsx
// Verifies loading/error/success states for the KB/doc summary card.
// The Pie chart is stubbed to a data-testid placeholder.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { KnowledgePanel } from "@/components/overview/KnowledgePanel";

vi.mock("@/services/screen", () => ({
  screenApi: { getKnowledge: vi.fn() },
}));
import { screenApi } from "@/services/screen";

vi.mock("@ant-design/charts", () => ({
  Pie: (props: { data: unknown[] }) => (
    <div data-testid="pie-chart" data-rows={JSON.stringify(props.data)} />
  ),
}));

const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{children}</ConfigProvider>
);

const sampleData = {
  total_kbs: 5,
  total_documents: 142,
  total_chunks: 3810,
  parse_success: 130,
  parse_failed: 8,
  embedding_failed: 4,
  by_status: [
    { status: "completed", count: 130 },
    { status: "failed", count: 12 },
  ],
};

describe("KnowledgePanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows loading first", () => {
    (screenApi.getKnowledge as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise(() => {}),
    );
    render(<KnowledgePanel />, { wrapper: TestWrapper });
    expect(document.querySelector(".ant-spin")).toBeTruthy();
  });

  it("shows error UI on failure", async () => {
    (screenApi.getKnowledge as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("kb fetch failed"),
    );
    render(<KnowledgePanel />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText(/kb fetch failed/)).toBeInTheDocument();
    });
  });

  it("renders the KB summary card on success", async () => {
    (screenApi.getKnowledge as ReturnType<typeof vi.fn>).mockResolvedValue(sampleData);
    render(<KnowledgePanel />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("知识库 / 文档")).toBeInTheDocument();
    });
    // Top stats row: KB / Doc / Chunk counts.
    expect(screen.getByText(/知识库: 5/)).toBeInTheDocument();
    expect(screen.getByText(/文档: 142/)).toBeInTheDocument();
    expect(screen.getByText(/Chunk: 3810/)).toBeInTheDocument();
    // Parse status row: success / failed / embedding_failed.
    expect(screen.getByText(/解析成功: 130/)).toBeInTheDocument();
    expect(screen.getByText(/失败: 8/)).toBeInTheDocument();
    expect(screen.getByText(/嵌入失败: 4/)).toBeInTheDocument();
  });

  it("passes by_status rows to the Pie chart", async () => {
    (screenApi.getKnowledge as ReturnType<typeof vi.fn>).mockResolvedValue(sampleData);
    render(<KnowledgePanel />, { wrapper: TestWrapper });
    await waitFor(() => {
      const pie = screen.getByTestId("pie-chart");
      const rows = JSON.parse(pie.getAttribute("data-rows") || "[]");
      expect(rows).toHaveLength(2);
      expect(rows[0]).toMatchObject({ status: "completed", count: 130 });
    });
  });
});
