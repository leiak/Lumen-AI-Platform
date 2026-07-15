import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { ConfigProvider, App as AntdApp } from "antd";
import React from "react";

import TemplatesPage from "@/app/dashboard/workflow/templates/page";

function TestWrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider><AntdApp>{children}</AntdApp></ConfigProvider>;
}

vi.mock("@/services/workflowTemplate", () => ({
  workflowTemplateApi: {
    list: vi.fn(),
    detail: vi.fn(),
    import: vi.fn(),
    categories: vi.fn(),
    publish: vi.fn(),
  },
}));

import { workflowTemplateApi } from "@/services/workflowTemplate";
const mockedList = workflowTemplateApi.list as unknown as ReturnType<typeof vi.fn>;
const mockedImport = workflowTemplateApi.import as unknown as ReturnType<typeof vi.fn>;
const mockedCategories = workflowTemplateApi.categories as unknown as ReturnType<typeof vi.fn>;

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  usePathname: () => "/dashboard/workflow/templates",
  useSearchParams: () => new URLSearchParams(),
}));

const sampleTemplates = [
  {
    id: 1,
    name: "模板 A",
    description: "first",
    category: "general",
    tags: ["a"],
    author_id: 1,
    author_name: "u1",
    downloads: 5,
    created_at: "2026-06-16",
  },
  {
    id: 2,
    name: "模板 B",
    description: "second",
    category: "rag",
    tags: ["rag"],
    author_id: 2,
    author_name: "u2",
    downloads: 10,
    created_at: "2026-06-16",
  },
];

describe("TemplatesPage", () => {
  beforeEach(() => {
    pushMock.mockReset();
    mockedList.mockReset();
    mockedImport.mockReset();
    mockedCategories.mockReset();
  });

  it("renders a card per template", async () => {
    mockedList.mockResolvedValue({
      data: { code: 200, data: sampleTemplates, total: 2 },
    });
    mockedCategories.mockResolvedValue({
      data: { code: 200, data: [] },
    });

    render(
      <TestWrapper>
        <TemplatesPage />
      </TestWrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("模板 A")).toBeTruthy();
    });
    expect(screen.getByText("模板 B")).toBeTruthy();
  });

  it("importing a template calls the api and routes to the workflow list", async () => {
    mockedList.mockResolvedValue({
      data: { code: 200, data: sampleTemplates, total: 2 },
    });
    mockedCategories.mockResolvedValue({
      data: { code: 200, data: [] },
    });
    mockedImport.mockResolvedValue({
      data: { code: 200, data: { workflow_id: 99, name: "模板 A" } },
    });

    render(
      <TestWrapper>
        <TemplatesPage />
      </TestWrapper>
    );
    await waitFor(() => {
      expect(screen.getByText("模板 A")).toBeTruthy();
    });

    // Click the import button on the first card. Cards in a grid
    // expose their actions inside .ant-card-actions. The 2nd action
    // (index 1) is the import button.
    const firstCard = document.querySelector(".ant-card");
    expect(firstCard).toBeTruthy();
    const importBtn = firstCard!.querySelectorAll(".ant-card-actions button")[1] as HTMLElement;
    expect(importBtn).toBeTruthy();
    fireEvent.click(importBtn);

    // Confirm modal OK button.
    await waitFor(() => {
      expect(screen.getByText("确认导入")).toBeTruthy();
    });
    fireEvent.click(screen.getByText("确认导入"));

    await waitFor(() => {
      expect(mockedImport).toHaveBeenCalledWith(1);
    });
    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/dashboard/workflow?selected=99");
    });
  });
});
