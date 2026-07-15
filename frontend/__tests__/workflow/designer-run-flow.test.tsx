// Designer run flow integration test: when the workflow has an input node
// with `variables: [{name: "custom", type: "string"}]`, clicking the
// "运行" button must open the InputValuesModal, then on confirm the run
// API call body must include { input_data: { custom: "<entered value>" } }.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider, App as AntdApp } from "antd";

// ReactFlow's ZoomPane uses ResizeObserver, which jsdom does not implement.
// Stub it before importing the page so the mount path doesn't blow up.
if (typeof window !== "undefined" && typeof (window as any).ResizeObserver === "undefined") {
  (window as any).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  (globalThis as any).ResizeObserver = (window as any).ResizeObserver;
}

// Mock the workflow service so we can spy on the run() call.
const runSpy = vi.fn().mockResolvedValue({
  data: { code: 200, data: { status: "completed", results: {}, final_output: { value: null } } },
});
vi.mock("@/services/workflow", () => ({
  workflowApi: {
    // The page reads res.data.data and calls .find() on it, so return an
    // array (not the PaginatedResponse.items shape). Include the workflow
    // whose id matches the mocked ?id=1 URL param so auto-load fires.
    list: vi.fn().mockResolvedValue({
      data: {
        code: 200,
        data: [
          {
            id: 1,
            name: "test",
            definition: {
              nodes: [
                { id: "n1", type: "input", config: { variables: [{ name: "custom", type: "string" }] }, position: { x: 0, y: 0 } },
                { id: "n2", type: "output", config: { field: "input.custom" }, position: { x: 0, y: 100 } },
              ],
              edges: [{ id: "e1", source: "n1", target: "n2" }],
            },
          },
        ],
        total: 1,
      },
    }),
    get: vi.fn().mockResolvedValue({
      data: {
        code: 200,
        data: {
          id: 1, name: "test", definition: {
            nodes: [
              { id: "n1", type: "input", config: { variables: [{ name: "custom", type: "string" }] }, position: { x: 0, y: 0 } },
              { id: "n2", type: "output", config: { field: "input.custom" }, position: { x: 0, y: 100 } },
            ],
            edges: [{ id: "e1", source: "n1", target: "n2" }],
          },
        },
      },
    }),
    run: (...args: any[]) => runSpy(...args),
  },
}));

import { useSearchParams } from "next/navigation";
vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: (k: string) => (k === "id" ? "1" : null) }),
}));

import WorkflowDesignerPage from "@/app/dashboard/workflow/designer/page";

function TestWrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider><AntdApp>{children}</AntdApp></ConfigProvider>;
}

describe("designer run flow with input variables", () => {
  beforeEach(() => {
    runSpy.mockClear();
  });

  it("opens the input modal, collects values, and calls run() with the right body", async () => {
    const user = userEvent.setup();
    render(
      <TestWrapper>
        <WorkflowDesignerPage />
      </TestWrapper>
    );
    // Wait for the workflow name to populate the Input — that proves the
    // list() → find() → handleWorkflowSelect() → loadWorkflow() chain
    // finished and the run button is safe to click. Using findByText on
    // the run button is flaky under full-suite load (5s timeout trips)
    // because the page is still mounting.
    await screen.findByDisplayValue("test", {}, { timeout: 15000 });
    const runBtn = screen.getByText(/^运行$/);
    fireEvent.click(runBtn);
    // Modal should appear with a field labelled "custom"
    const label = await screen.findByText("custom");
    expect(label).toBeTruthy();
    // AntD Form.Item with label={v.name} creates htmlFor="custom" on the
    // label and cloneElement-injects id="custom" on the input child, so
    // getByLabelText reaches the real <input> reliably.
    const input = (await screen.findByLabelText("custom")) as HTMLInputElement;
    await user.type(input, "hello");
    fireEvent.click(screen.getByRole("button", { name: /确\s*定/ }));
    await waitFor(() => {
      expect(runSpy).toHaveBeenCalledTimes(1);
    });
    expect(runSpy.mock.calls[0]).toEqual([1, { custom: "hello" }]);
  }, 30000);
});
