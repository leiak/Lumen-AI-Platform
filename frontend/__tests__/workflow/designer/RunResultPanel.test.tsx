import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConfigProvider, App as AntdApp } from "antd";
import { RunResultPanel } from "@/components/workflow/designer/RunResultPanel";

// TestWrapper mirrors dashboard layout.tsx — App.useApp() needs the
// ConfigProvider + App context to render, otherwise the static message API
// emits a console warning and component sub-trees that depend on theme
// tokens behave inconsistently.
function TestWrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider><AntdApp>{children}</AntdApp></ConfigProvider>;
}

// The real backend returns a WorkflowRunResponse (see backend
// app/schemas/workflow.py::WorkflowRunResponse): the executor's output is
// nested under `output_data`, NOT spread at the top level. The previous
// shape in this test was a lie that matched a bug: the panel was reading
// result.results / result.final_output and finding them undefined, so
// users only saw the status tag. This test now mirrors the actual API
// payload so a regression to the old read path makes the test fail.
const sampleResult = {
  id: 241,
  workflow_id: 1,
  status: "completed",
  trigger_source: "manual",
  input_data: {},
  output_data: {
    status: "completed",
    results: {
      "4ffb4d10-3344-4c56-88cb-c82860f7f516": {
        error: null,
        node_id: "4ffb4d10-3344-4c56-88cb-c82860f7f516",
        outputs: [
          { name: "response", type: "string" },
          { name: "model", type: "string" },
        ],
        output_values: {
          model: "MiniMax-M2.7-highspeed",
          response:
            "content='Translated text.' additional_kwargs={} name='Bot' id='r-1'",
        },
      },
    },
    // final_output.value is intentionally a DIFFERENT string from the LLM
    // response so the two <pre> blocks render distinct text — otherwise
    // getByText("Translated text.") below would match both elements and fail.
    final_output: { value: "[workflow end]", outputs: { value: "[workflow end]" } },
  },
  error_message: null,
};

describe("RunResultPanel", () => {
  it("renders the status tag from the result", () => {
    render(
      <TestWrapper>
        <RunResultPanel result={sampleResult} loading={false} error={null} onClose={vi.fn()} />
      </TestWrapper>
    );
    // M30c: status appears both at the run level AND on each per-node
    // card. Use getAllByText to assert "at least one" without
    // caring which copy wins.
    expect(screen.getAllByText("completed").length).toBeGreaterThan(0);
  });

  it("renders the LLM response content extracted from AIMessage string", () => {
    render(
      <TestWrapper>
        <RunResultPanel result={sampleResult} loading={false} error={null} onClose={vi.fn()} />
      </TestWrapper>
    );
    expect(screen.getByText("Translated text.")).toBeTruthy();
  });

  it("does NOT show the 'no LLM node triggered' empty state when an LLM has a response", () => {
    render(
      <TestWrapper>
        <RunResultPanel result={sampleResult} loading={false} error={null} onClose={vi.fn()} />
      </TestWrapper>
    );
    expect(screen.queryByText("本次执行未触发 LLM 节点")).toBeNull();
  });
});
