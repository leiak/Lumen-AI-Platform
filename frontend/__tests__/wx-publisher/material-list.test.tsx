// frontend/__tests__/wx-publisher/material-list.test.tsx
// M32 — 公众号助手 — Material page tests.
// 3 cases: List 渲染 / KB 选材 Modal / 标签过滤.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";
import MaterialsPage from "@/app/dashboard/wx-publisher/materials/page";

const hoisted = vi.hoisted(() => ({
  listMock: vi.fn(),
  deleteMock: vi.fn(),
  createMock: vi.fn(),
  importFromKBMock: vi.fn(),
  knowledgeListMock: vi.fn(),
}));

vi.mock("@/services/wx-publisher", () => ({
  draftApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), delete: vi.fn(), addSection: vi.fn(), updateSection: vi.fn(), deleteSection: vi.fn(), reorderSections: vi.fn() },
  accountApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), delete: vi.fn(), verify: vi.fn() },
  templateApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), delete: vi.fn(), thumbnailPath: (id: number) => `/x/${id}` },
  draftAiApi: { outline: vi.fn(), rewrite: vi.fn(), expand: vi.fn(), title: vi.fn(), render: vi.fn() },
  materialApi: {
    list: hoisted.listMock,
    get: vi.fn(),
    create: hoisted.createMock,
    delete: hoisted.deleteMock,
    importFromKB: hoisted.importFromKBMock,
  },
  publishApi: { createPublish: vi.fn(), getPublish: vi.fn() },
}));

vi.mock("@/services/knowledge", () => ({
  knowledgeApi: {
    list: hoisted.knowledgeListMock,
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useParams: () => ({ id: "1" }),
  usePathname: () => "/dashboard/wx-publisher/materials",
}));

const sampleMaterials = [
  { id: 1, title: "AI 数据点 1", content_preview: "AI 行业增长 30%...", source_type: "kb", kb_chunk_id: 100, tags: ["AI", "行业"], is_used: false, created_at: "2026-06-17T08:00:00Z" },
  { id: 2, title: "我的手动笔记", content_preview: "手动整理的洞察...", source_type: "manual", kb_chunk_id: null, tags: ["笔记"], is_used: true, created_at: "2026-06-17T09:00:00Z" },
];

describe("MaterialsPage", () => {
  beforeEach(() => {
    hoisted.listMock.mockReset();
    hoisted.deleteMock.mockReset();
    hoisted.createMock.mockReset();
    hoisted.importFromKBMock.mockReset();
    hoisted.knowledgeListMock.mockReset();

    hoisted.listMock.mockResolvedValue({
      items: sampleMaterials,
      total: 2,
      page: 1,
      page_size: 20,
    });
    hoisted.knowledgeListMock.mockResolvedValue({
      data: { code: 200, message: "ok", data: [{ id: 1, name: "KB-Test" }], total: 1, page: 1, page_size: 100 },
    });
  });

  it("renders material list with sources and tags", async () => {
    render(<TestWrapper><MaterialsPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("AI 数据点 1")).toBeInTheDocument());
    expect(screen.getByText("我的手动笔记")).toBeInTheDocument();
    // source tags
    expect(screen.getByText("知识库")).toBeInTheDocument();
    expect(screen.getByText("手动")).toBeInTheDocument();
  });

  it("opens KB import modal when button clicked", async () => {
    render(<TestWrapper><MaterialsPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("AI 数据点 1")).toBeInTheDocument());
    fireEvent.click(screen.getByText("从 KB 选材"));
    await waitFor(() => expect(screen.getByText("从知识库选材")).toBeInTheDocument());
  });

  it("sends source_type filter to API when changed", async () => {
    render(<TestWrapper><MaterialsPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("AI 数据点 1")).toBeInTheDocument());
    // AntD Select — placeholder span → 找到 .ant-select-selector 容器,
    // mouseDown 触发 dropdown.
    const placeholderSpan = Array.from(
      document.querySelectorAll(".ant-select-selection-placeholder")
    ).find((el) => el.textContent === "来源");
    expect(placeholderSpan).toBeDefined();
    const selectorDiv = placeholderSpan!.closest(".ant-select-selector")!;
    fireEvent.mouseDown(selectorDiv);

    // 等待 dropdown 出现 — 在 dropdown 容器内找 .ant-select-item-option,
    // 避免与列表中"知识库"Tag 撞.
    await waitFor(() => {
      const dropdown = document.querySelector(".ant-select-dropdown");
      expect(dropdown).not.toBeNull();
    });
    const dropdownOptions = document.querySelectorAll(
      ".ant-select-dropdown .ant-select-item-option"
    );
    expect(dropdownOptions.length).toBeGreaterThan(0);
    // 第一个选项是 "知识库" (按定义顺序).
    fireEvent.click(dropdownOptions[0]);
    await waitFor(() => {
      const calls = hoisted.listMock.mock.calls;
      const lastCall = calls[calls.length - 1][0];
      expect(lastCall).toMatchObject({ source_type: "kb" });
    });
  });
});