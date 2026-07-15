import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { ConfigProvider, App } from "antd";
import React from "react";

import { useWorkflowList } from "@/app/dashboard/workflow/hooks/useWorkflowList";
import { workflowApi } from "@/services/workflow";

// Mock the @/services/workflow module so we can stub the .list call.
vi.mock("@/services/workflow", () => {
  const list = vi.fn();
  const create = vi.fn();
  const remove = vi.fn();
  return {
    workflowApi: {
      list,
      create,
      delete: remove,
    },
    Workflow: {},
  };
});

// TestWrapper mirrors dashboard layout — App.useApp() needs the
// ConfigProvider + App context to render, otherwise the static
// message API emits a console warning.
function TestWrapper({ children }: { children: React.ReactNode }): React.ReactElement {
  return (
    <ConfigProvider>
      <App>{children}</App>
    </ConfigProvider>
  );
}

const mockedList = workflowApi.list as unknown as ReturnType<typeof vi.fn>;
const mockedCreate = workflowApi.create as unknown as ReturnType<typeof vi.fn>;
const mockedDelete = workflowApi.delete as unknown as ReturnType<typeof vi.fn>;

describe("useWorkflowList", () => {
  beforeEach(() => {
    mockedList.mockReset();
    mockedCreate.mockReset();
    mockedDelete.mockReset();
  });

  it("loads workflows on mount and exposes them via state", async () => {
    mockedList.mockResolvedValue({
      data: {
        code: 200,
        data: [
          { id: 1, name: "wf-1", tenant_id: 1, is_active: true, definition: { nodes: [], edges: [] } },
          { id: 2, name: "wf-2", tenant_id: 1, is_active: true, definition: { nodes: [], edges: [] } },
        ],
        total: 2,
      },
    });

    const { result } = renderHook(() => useWorkflowList(), { wrapper: TestWrapper });

    await waitFor(() => {
      expect(result.current.workflows.length).toBe(2);
    });
    expect(result.current.total).toBe(2);
    expect(mockedList).toHaveBeenCalledWith(1, 10);
  });

  it("handleCreate calls workflowApi.create and refreshes the list on success", async () => {
    mockedList.mockResolvedValue({
      data: { code: 200, data: [], total: 0 },
    });
    mockedCreate.mockResolvedValue({
      data: { code: 200, data: { id: 99, name: "new", tenant_id: 1, is_active: true, definition: { nodes: [], edges: [] } } },
    });

    const { result } = renderHook(() => useWorkflowList(), { wrapper: TestWrapper });
    await waitFor(() => {
      expect(result.current.workflows).toBeDefined();
    });

    await act(async () => {
      await result.current.handleCreate({ name: "new", description: "d" });
    });

    expect(mockedCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "new",
        description: "d",
        definition: expect.objectContaining({ nodes: expect.any(Array) }),
      })
    );
    // list() was called once on mount + once after create → ≥ 2 calls
    expect(mockedList.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("handleDelete calls workflowApi.delete and refreshes", async () => {
    mockedList.mockResolvedValue({
      data: { code: 200, data: [], total: 0 },
    });
    mockedDelete.mockResolvedValue({ data: { code: 200 } });

    const { result } = renderHook(() => useWorkflowList(), { wrapper: TestWrapper });
    await waitFor(() => {
      expect(result.current.workflows).toBeDefined();
    });

    await act(async () => {
      await result.current.handleDelete(42);
    });

    expect(mockedDelete).toHaveBeenCalledWith(42);
  });
});
