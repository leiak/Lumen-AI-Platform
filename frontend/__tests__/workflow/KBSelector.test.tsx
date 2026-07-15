import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { KBSelector } from "@/components/workflow/KBSelector";

// Mock the existing knowledge service. Spec drift: the P2 plan assumed a
// brand-new `services/knowledgeBase.ts` with `knowledgeBaseApi.list({ active: true })`
// and `is_active: boolean` fields, but the project already exposes
// `knowledgeApi.list(page, pageSize)` in `services/knowledge.ts` with a
// paginated envelope and `status: "active" | "inactive"` (no `is_active`).
// We import the existing service and filter `status === "active"` in the
// component (mirroring how `ToolSelector` filters `is_enabled`).
vi.mock("@/services/knowledge", () => ({
  knowledgeApi: {
    list: vi.fn(),
  },
}));

import { knowledgeApi } from "@/services/knowledge";

const wrap = (ui: React.ReactNode) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{ui}</ConfigProvider>
);

describe("KBSelector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists only active KBs and filters out inactive ones", async () => {
    (knowledgeApi.list as any).mockResolvedValue({
      data: {
        code: 200,
        data: [
          {
            id: 1,
            name: "产品手册",
            status: "active",
            tenant_id: 1,
            embedding_model: "nomic-embed-text",
            created_at: "2026-06-01T00:00:00",
            document_count: 3,
          },
          {
            id: 2,
            name: "旧知识库",
            status: "inactive",
            tenant_id: 1,
            embedding_model: "nomic-embed-text",
            created_at: "2026-05-01T00:00:00",
            document_count: 0,
          },
        ],
        total: 2,
        page: 1,
        page_size: 10,
      },
    });

    render(
      wrap(<KBSelector value={null} kbNameCache="" onChange={() => {}} />)
    );

    fireEvent.mouseDown(screen.getByRole("combobox"));
    await waitFor(() => {
      expect(screen.getByText("产品手册")).toBeInTheDocument();
    });
    expect(screen.queryByText("旧知识库")).not.toBeInTheDocument();
  });

  it("calls onChange with the picked KB id and name", async () => {
    (knowledgeApi.list as any).mockResolvedValue({
      data: {
        code: 200,
        data: [
          {
            id: 7,
            name: "法规库",
            status: "active",
            tenant_id: 1,
            embedding_model: "nomic-embed-text",
            created_at: "2026-06-01T00:00:00",
            document_count: 5,
          },
        ],
        total: 1,
        page: 1,
        page_size: 10,
      },
    });

    const onChange = vi.fn();
    render(
      wrap(<KBSelector value={null} kbNameCache="" onChange={onChange} />)
    );

    fireEvent.mouseDown(screen.getByRole("combobox"));
    await waitFor(() => screen.getByText("法规库"));
    fireEvent.click(screen.getByText("法规库"));
    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith(7, "法规库");
    });
  });

  it("shows the missing yellow entry when value references a deleted KB", async () => {
    (knowledgeApi.list as any).mockResolvedValue({
      data: {
        code: 200,
        data: [
          {
            id: 1,
            name: "产品手册",
            status: "active",
            tenant_id: 1,
            embedding_model: "nomic-embed-text",
            created_at: "2026-06-01T00:00:00",
            document_count: 3,
          },
        ],
        total: 1,
        page: 1,
        page_size: 10,
      },
    });

    render(
      wrap(
        <KBSelector value={999} kbNameCache="已删除KB" onChange={() => {}} />
      )
    );

    // The cached name surfaces in the warning row below the Select
    expect(screen.getByText(/原知识库已失效/)).toBeInTheDocument();

    // Opening the dropdown reveals the missing-sentinel option
    fireEvent.mouseDown(screen.getByRole("combobox"));
    await waitFor(() => {
      expect(
        screen.getByRole("option", { name: /已删除/ })
      ).toBeInTheDocument();
    });
  });

  it("shows an error Alert when knowledgeApi.list fails", async () => {
    (knowledgeApi.list as any).mockRejectedValue(new Error("network"));

    render(
      wrap(<KBSelector value={null} kbNameCache="" onChange={() => {}} />)
    );

    await waitFor(() => {
      expect(screen.getByText(/知识库数据加载失败/i)).toBeInTheDocument();
    });
  });
});
