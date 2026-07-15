import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { HTTPPanel } from "@/components/workflow/nodes/http/Panel";
import type { WorkflowNode } from "@/services/workflow";

vi.mock("@/services/nodes", () => ({
  nodesApi: { previewHTTP: vi.fn() },
}));

const wrap = (ui: React.ReactNode) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{ui}</ConfigProvider>
);

const baseNode: WorkflowNode = {
  id: "h1",
  type: "http",
  position: { x: 0, y: 0 },
  data: {},
  config: { method: "GET", url: "https://api.example.com" },
};

describe("HTTPPanel", () => {
  it("renders method and URL fields", () => {
    render(
      wrap(
        <HTTPPanel
          node={baseNode}
          nodes={[]}
          edges={[]}
          onChange={() => {}}
        />
      )
    );
    expect(
      screen.getByDisplayValue("https://api.example.com")
    ).toBeInTheDocument();
  });

  it("calls onChange when URL edited (debounced 200ms)", async () => {
    const onChange = vi.fn();
    render(
      wrap(
        <HTTPPanel
          node={baseNode}
          nodes={[]}
          edges={[]}
          onChange={onChange}
        />
      )
    );
    fireEvent.change(screen.getByDisplayValue("https://api.example.com"), {
      target: { value: "https://other.com" },
    });
    // 收口-A: debounced onChange — wait for the 200ms timer to fire.
    await waitFor(() => expect(onChange).toHaveBeenCalled(), { timeout: 500 });
    const cfg = onChange.mock.calls[0][0].config;
    expect(cfg.url).toBe("https://other.com");
  });

  it("shows auth section", () => {
    render(
      wrap(
        <HTTPPanel
          node={baseNode}
          nodes={[]}
          edges={[]}
          onChange={() => {}}
        />
      )
    );
    expect(screen.getByText("鉴权")).toBeInTheDocument();
  });

  it("shows advanced options", () => {
    render(
      wrap(
        <HTTPPanel
          node={baseNode}
          nodes={[]}
          edges={[]}
          onChange={() => {}}
        />
      )
    );
    expect(screen.getByText(/高级选项/)).toBeInTheDocument();
  });

  it("test request button calls previewHTTP", async () => {
    const { nodesApi } = await import("@/services/nodes");
    (nodesApi.previewHTTP as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { code: 200, data: { status_code: 200 } },
    });
    render(
      wrap(
        <HTTPPanel
          node={baseNode}
          nodes={[]}
          edges={[]}
          onChange={() => {}}
        />
      )
    );
    fireEvent.click(screen.getByText("测试请求"));
    expect(nodesApi.previewHTTP).toHaveBeenCalled();
  });
});
