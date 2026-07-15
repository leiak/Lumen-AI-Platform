import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ConfigProvider, App as AntdApp } from "antd";
import React from "react";

// M30b: WorkflowTable uses useRouter() for the design-button click.
// Mock it so the test doesn't need a Next.js app router context.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/dashboard/workflow",
  useSearchParams: () => new URLSearchParams(),
}));

import { WorkflowTable } from "@/app/dashboard/workflow/components/WorkflowTable";
import type { Workflow } from "@/services/workflow";

function TestWrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider><AntdApp>{children}</AntdApp></ConfigProvider>;
}

const sampleWorkflows: Workflow[] = [
  {
    id: 1,
    name: "Test Workflow",
    description: "Test",
    tenant_id: 1,
    is_active: true,
    created_at: "2026-06-16T10:00:00",
    definition: { nodes: [], edges: [] },
  },
];

describe("WorkflowTable", () => {
  it("renders a row per workflow with the name visible", () => {
    render(
      <TestWrapper>
        <WorkflowTable
          workflows={sampleWorkflows}
          loading={false}
          page={1}
          pageSize={10}
          total={1}
          runningId={null}
          publishingId={null}
          onPageChange={vi.fn()}
          onRun={vi.fn()}
          onEditSchedules={vi.fn()}
          onViewHistory={vi.fn()}
          onPublishTemplate={vi.fn()}
          onDelete={vi.fn()}
        />
      </TestWrapper>
    );
    expect(screen.getByText("Test Workflow")).toBeTruthy();
  });

  it("calls onRun when the run button is clicked", () => {
    const onRun = vi.fn();
    render(
      <TestWrapper>
        <WorkflowTable
          workflows={sampleWorkflows}
          loading={false}
          page={1}
          pageSize={10}
          total={1}
          runningId={null}
          publishingId={null}
          onPageChange={vi.fn()}
          onRun={onRun}
          onEditSchedules={vi.fn()}
          onViewHistory={vi.fn()}
          onPublishTemplate={vi.fn()}
          onDelete={vi.fn()}
        />
      </TestWrapper>
    );
    // The run button is the primary button in the row. Find by
    // ant-btn-primary class.
    const runBtn = document.querySelector(
      "button.ant-btn-primary"
    ) as HTMLElement;
    expect(runBtn).toBeTruthy();
    fireEvent.click(runBtn);
    expect(onRun).toHaveBeenCalledWith(1);
  });

  it("renders the delete (danger) button for each row", () => {
    render(
      <TestWrapper>
        <WorkflowTable
          workflows={sampleWorkflows}
          loading={false}
          page={1}
          pageSize={10}
          total={1}
          runningId={null}
          publishingId={null}
          onPageChange={vi.fn()}
          onRun={vi.fn()}
          onEditSchedules={vi.fn()}
          onViewHistory={vi.fn()}
          onPublishTemplate={vi.fn()}
          onDelete={vi.fn()}
        />
      </TestWrapper>
    );
    // The delete (danger) button is the only one with the
    // ant-btn-dangerous class. We don't fire the click here because
    // AntD's Popconfirm renders in a portal that jsdom doesn't
    // always mount in unit tests — the popconfirm integration is
    // covered by the e2e smoke in M30a.
    const deleteBtn = document.querySelector(
      "button.ant-btn-dangerous"
    ) as HTMLElement;
    expect(deleteBtn).toBeTruthy();
  });
});
