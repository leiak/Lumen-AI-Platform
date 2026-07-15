import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { ConfigProvider, App as AntdApp } from "antd";
import React from "react";

import { useWorkflowRuns } from "@/app/dashboard/workflow/hooks/useWorkflowRuns";

function TestWrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider><AntdApp>{children}</AntdApp></ConfigProvider>;
}

vi.mock("@/services/workflow", () => ({
  workflowApi: {
    listRuns: vi.fn(),
    listRunNodes: vi.fn(),
  },
  WorkflowRun: {},
  WorkflowNodeRun: {},
}));

import { workflowApi } from "@/services/workflow";
const mockedListRuns = workflowApi.listRuns as unknown as ReturnType<typeof vi.fn>;
const mockedListRunNodes = workflowApi.listRunNodes as unknown as ReturnType<typeof vi.fn>;

describe("useWorkflowRuns", () => {
  beforeEach(() => {
    mockedListRuns.mockReset();
    mockedListRunNodes.mockReset();
  });

  it("openHistory triggers a fetch and stores runs", async () => {
    mockedListRuns.mockResolvedValue({
      data: { code: 200, data: [{ id: 1, workflow_id: 7, status: "completed" }], total: 1 },
    });

    const { result } = renderHook(() => useWorkflowRuns(), { wrapper: TestWrapper });
    act(() => {
      result.current.openHistory(7, "wf-7");
    });
    await waitFor(() => {
      expect(result.current.historyRuns.length).toBe(1);
    });
    expect(mockedListRuns).toHaveBeenCalledWith(7, 1, 10);
  });

  it("openRunDetail fetches the per-node list", async () => {
    mockedListRuns.mockResolvedValue({
      data: { code: 200, data: [{ id: 1, workflow_id: 7, status: "completed" }], total: 1 },
    });
    mockedListRunNodes.mockResolvedValue({
      data: {
        code: 200,
        data: [
          { id: 100, run_id: 1, node_id: "a", node_type: "input", status: "completed" },
        ],
      },
    });

    const { result } = renderHook(() => useWorkflowRuns(), { wrapper: TestWrapper });
    act(() => {
      result.current.openHistory(7, "wf-7");
    });
    await waitFor(() => {
      expect(result.current.historyRuns.length).toBe(1);
    });
    await act(async () => {
      await result.current.openRunDetail({ id: 1, workflow_id: 7, status: "completed" });
    });
    await waitFor(() => {
      expect(result.current.detailNodeRuns.length).toBe(1);
    });
    expect(mockedListRunNodes).toHaveBeenCalledWith(7, 1);
  });
});
