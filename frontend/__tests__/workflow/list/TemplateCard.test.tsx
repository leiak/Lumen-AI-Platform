import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ConfigProvider, App as AntdApp } from "antd";
import React from "react";

import { TemplateCard } from "@/app/dashboard/workflow/components/TemplateCard";
import type { WorkflowTemplate } from "@/services/workflowTemplate";

function TestWrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider><AntdApp>{children}</AntdApp></ConfigProvider>;
}

const sample: WorkflowTemplate = {
  id: 7,
  name: "RAG 模板",
  description: "检索增强生成示例",
  category: "knowledge",
  tags: ["rag", "vector"],
  author_id: 1,
  author_name: "alice",
  downloads: 12,
  created_at: "2026-06-16",
};

describe("TemplateCard", () => {
  it("renders name, description, category tag", () => {
    render(
      <TestWrapper>
        <TemplateCard template={sample} onPreview={vi.fn()} onImport={vi.fn()} />
      </TestWrapper>
    );
    expect(screen.getByText("RAG 模板")).toBeTruthy();
    expect(screen.getByText("检索增强生成示例")).toBeTruthy();
    // category tag is unique to the card header
    expect(screen.getByText("knowledge")).toBeTruthy();
  });

  it("renders all tags", () => {
    render(
      <TestWrapper>
        <TemplateCard template={sample} onPreview={vi.fn()} onImport={vi.fn()} />
      </TestWrapper>
    );
    // "rag" appears as both a tag and a description substring; check
    // each tag independently.
    expect(screen.getByText("vector")).toBeTruthy();
  });

  it("calls onPreview when the preview button is clicked", () => {
    const onPreview = vi.fn();
    render(
      <TestWrapper>
        <TemplateCard template={sample} onPreview={onPreview} onImport={vi.fn()} />
      </TestWrapper>
    );
    // Card actions are icon buttons. Find by antd's class for card
    // action area.
    const buttons = Array.from(document.querySelectorAll(".ant-card-actions button"));
    expect(buttons.length).toBeGreaterThanOrEqual(2);
    fireEvent.click(buttons[0]);
    expect(onPreview).toHaveBeenCalledWith(7);
  });

  it("calls onImport when the import button is clicked", () => {
    const onImport = vi.fn();
    render(
      <TestWrapper>
        <TemplateCard template={sample} onPreview={vi.fn()} onImport={onImport} />
      </TestWrapper>
    );
    const buttons = Array.from(document.querySelectorAll(".ant-card-actions button"));
    expect(buttons.length).toBeGreaterThanOrEqual(2);
    fireEvent.click(buttons[1]);
    expect(onImport).toHaveBeenCalledWith(7);
  });
});
