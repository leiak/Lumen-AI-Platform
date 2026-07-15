import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConfigProvider, App as AntdApp } from "antd";
import React from "react";

import { RunResultPanel } from "@/components/workflow/designer/RunResultPanel";
import type { WorkflowNodeRun } from "@/services/workflow";

function TestWrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider><AntdApp>{children}</AntdApp></ConfigProvider>;
}

const sampleNodeRuns: WorkflowNodeRun[] = [
  {
    id: 1,
    run_id: 100,
    node_id: "input_1",
    node_type: "input",
    status: "completed",
    started_at: "2026-06-16T10:00:00.000Z",
    finished_at: "2026-06-16T10:00:00.100Z",
    execution_order: 0,
    input_data: { x: "hi" },
    output_data: { x: "hi" },
    error_message: null,
  },
  {
    id: 2,
    run_id: 100,
    node_id: "llm_1",
    node_type: "llm",
    status: "failed",
    started_at: "2026-06-16T10:00:00.200Z",
    finished_at: "2026-06-16T10:00:00.500Z",
    execution_order: 1,
    input_data: { prompt: "echo hi" },
    output_data: null,
    error_message: "synthetic LLM boom",
  },
];

describe("RunResultPanel M30c timeline", () => {
  it("renders one card per WorkflowNodeRun, in execution_order", () => {
    const result = {
      id: 100,
      workflow_id: 1,
      status: "failed",
      input_data: {},
      output_data: { results: {}, final_output: null },
      error_message: "synthetic LLM boom",
    };
    render(
      <TestWrapper>
        <RunResultPanel
          result={result}
          loading={false}
          error={null}
          nodeRuns={sampleNodeRuns}
          onClose={vi.fn()}
        />
      </TestWrapper>
    );
    // Both node types render as a tag inside a Card title.
    expect(screen.getByText("input_1")).toBeTruthy();
    expect(screen.getByText("llm_1")).toBeTruthy();
    // Status tag for the failed node is visible.
    expect(screen.getAllByText("failed").length).toBeGreaterThan(0);
  });

  it("shows the M30a timeline tag when nodeRuns is provided", () => {
    const result = { status: "completed", output_data: { results: {} } };
    render(
      <TestWrapper>
        <RunResultPanel
          result={result}
          loading={false}
          error={null}
          nodeRuns={sampleNodeRuns}
          onClose={vi.fn()}
        />
      </TestWrapper>
    );
    expect(screen.getByText("M30a timeline")).toBeTruthy();
  });

  it("falls back to output_data.results when no nodeRuns is provided", () => {
    const result = {
      status: "completed",
      output_data: {
        results: {
          "input_1": {
            node_id: "input_1",
            output_values: { x: "hi" },
          },
        },
        final_output: null,
      },
    };
    render(
      <TestWrapper>
        <RunResultPanel
          result={result}
          loading={false}
          error={null}
          nodeRuns={null}
          onClose={vi.fn()}
        />
      </TestWrapper>
    );
    // input_1 should still appear (synthesized from results map).
    expect(screen.getByText("input_1")).toBeTruthy();
  });

  it("renders the empty state when no result is provided", () => {
    render(
      <TestWrapper>
        <RunResultPanel
          result={null}
          loading={false}
          error={null}
          onClose={vi.fn()}
        />
      </TestWrapper>
    );
    expect(screen.getByText(/尚未运行/)).toBeTruthy();
  });

  it("renders the error alert when an error string is provided", () => {
    render(
      <TestWrapper>
        <RunResultPanel
          result={null}
          loading={false}
          error="backend is down"
          onClose={vi.fn()}
        />
      </TestWrapper>
    );
    expect(screen.getByText("backend is down")).toBeTruthy();
  });
});
