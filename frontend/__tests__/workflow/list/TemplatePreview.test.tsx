import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ConfigProvider, App as AntdApp } from "antd";
import React from "react";

import { TemplatePreview } from "@/app/dashboard/workflow/components/TemplatePreview";

function TestWrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider><AntdApp>{children}</AntdApp></ConfigProvider>;
}

vi.mock("@/services/workflowTemplate", () => ({
  workflowTemplateApi: {
    detail: vi.fn(),
  },
}));

import { workflowTemplateApi } from "@/services/workflowTemplate";
const mockedDetail = workflowTemplateApi.detail as unknown as ReturnType<typeof vi.fn>;

const sample = {
  id: 3,
  name: "Demo",
  description: "D",
  category: "general",
  tags: ["a", "b"],
  author_id: 1,
  author_name: "u",
  downloads: 1,
  created_at: "2026-06-16",
  workflow_json: {
    nodes: [
      { id: "in", type: "input", config: {} },
      { id: "out", type: "output", config: {} },
    ],
    edges: [{ id: "e1", source: "in", target: "out" }],
  },
};

describe("TemplatePreview", () => {
  beforeEach(() => {
    mockedDetail.mockReset();
  });

  it("does not call detail() when templateId is null", () => {
    render(
      <TestWrapper>
        <TemplatePreview templateId={null} onClose={vi.fn()} />
      </TestWrapper>
    );
    expect(mockedDetail).not.toHaveBeenCalled();
  });

  it("loads + displays nodes and edges when templateId is set", async () => {
    mockedDetail.mockResolvedValue({
      data: { code: 200, data: sample },
    });
    render(
      <TestWrapper>
        <TemplatePreview templateId={3} onClose={vi.fn()} />
      </TestWrapper>
    );
    await waitFor(() => {
      expect(screen.getByText("Demo")).toBeTruthy();
    });
    // nodes are rendered as <code> in compact cards. "in" and "out"
    // may appear in multiple elements (e.g. edges), so use the
    // ant-tag content for the unique type label.
    expect(screen.getAllByText("input").length).toBeGreaterThan(0);
    expect(screen.getAllByText("output").length).toBeGreaterThan(0);
  });
});
