// frontend/__tests__/wx-publisher/kb-import-modal.test.tsx
// M32 — 公众号助手 — KBImportModal bug fix regression tests.
//
// Bug (2026-06-18): KBImportModal.handleSearch was a placeholder that
// called ``materialApi.list`` (列素材库) instead of
// ``knowledgeApi.search`` (走 M28 RetrievalPipeline). 后果:
//   1. 检索后看不到 KB 真实 chunk — 列表是空的 (用户没导入过素材时)
//   2. 检索后看到的是全部素材 (manual + kb 混合), 而不是 KB 命中
//
// 修法: handleSearch 改调 knowledgeApi.search(kbId, query, { k: topK }),
// 导入用 top_k (slider 值) 而非 selectedIds.length (后端不支持 per-chunk
// 选, 选 checkbox 仅作视觉反馈).
//
// 这些 case 锁住 fix, 防止 subagent 退化回到 placeholder 实现.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";
import { KBImportModal } from "@/components/wx-publisher/KBImportModal";

// AntD Button 把文字拆 2 span ("检" + "索"), textContent 中间有空格.
// 用这 helper 移除所有空白后比对, 比 includes("检索") 更稳.
const btnText = (b: HTMLButtonElement) => b.textContent?.replace(/\s/g, "") ?? "";
const findBtnByText = (text: string) =>
  Array.from(document.querySelectorAll("button")).find(
    (b) => btnText(b as HTMLButtonElement) === text
  );

const hoisted = vi.hoisted(() => ({
  importFromKBMock: vi.fn(),
  knowledgeSearchMock: vi.fn(),
}));

vi.mock("@/services/wx-publisher", () => ({
  materialApi: {
    list: vi.fn(),
    importFromKB: hoisted.importFromKBMock,
  },
}));

vi.mock("@/services/knowledge", () => ({
  knowledgeApi: {
    search: hoisted.knowledgeSearchMock,
  },
}));

const kbList = [{ id: 7, name: "KB-Test", tenant_id: 1 }];

// 模拟 M28 /api/v1/knowledge/{kb_id}/search 的响应 — 直接返 data 数组
// (search 端点不走分页, 返 `data: [...]`).
const kbResponse = (data: any[]) => ({
  data: { code: 200, message: "ok", data },
});

describe("KBImportModal — 检索修复", () => {
  beforeEach(() => {
    hoisted.importFromKBMock.mockReset();
    hoisted.knowledgeSearchMock.mockReset();
  });

  it("点击「检索」调 knowledgeApi.search, 不调 materialApi.list", async () => {
    hoisted.knowledgeSearchMock.mockResolvedValue(kbResponse([]));
    render(
      <TestWrapper>
        <KBImportModal open onClose={vi.fn()} kbList={kbList} />
      </TestWrapper>
    );
    // 选 KB + 输入 query
    // AntD Select — 找第一个 .ant-select (KB 下拉)
    const selects = document.querySelectorAll(".ant-select-selector");
    fireEvent.mouseDown(selects[0]);
    await waitFor(() => {
      const opts = document.querySelectorAll(
        ".ant-select-dropdown .ant-select-item-option"
      );
      expect(opts.length).toBeGreaterThan(0);
    });
    fireEvent.click(
      document.querySelectorAll(".ant-select-dropdown .ant-select-item-option")[0]
    );
    // 输入 query
    const input = screen.getByPlaceholderText(/搜索 query/);
    fireEvent.change(input, { target: { value: "AI Agent" } });
    // 点检索 — Modal 在 portal 里, AntD Button 把 "检" "索" 拆 2 个 span,
    // textContent 含空格, 用 btnText helper 移除空格比对
    const searchBtn = findBtnByText("检索");
    expect(searchBtn).toBeDefined();
    fireEvent.click(searchBtn!);
    await waitFor(() => {
      expect(hoisted.knowledgeSearchMock).toHaveBeenCalledWith(7, "AI Agent", {
        k: 20,
      });
    });
  });

  it("search 返回 KB chunk 后渲染结果列表, 不显示 manual 素材", async () => {
    // 模拟 KB 检索返 2 条 chunk (有 chunk_id 和 content)
    hoisted.knowledgeSearchMock.mockResolvedValue(
      kbResponse([
        { chunk_id: 101, content: "RAG 是检索增强生成\n用于提升 LLM 准确性" },
        { chunk_id: 102, content: "向量数据库选型: FAISS / ES / Milvus" },
      ])
    );
    render(
      <TestWrapper>
        <KBImportModal open onClose={vi.fn()} kbList={kbList} />
      </TestWrapper>
    );
    // 选 KB
    const selects = document.querySelectorAll(".ant-select-selector");
    fireEvent.mouseDown(selects[0]);
    await waitFor(() => {
      const opts = document.querySelectorAll(
        ".ant-select-dropdown .ant-select-item-option"
      );
      expect(opts.length).toBeGreaterThan(0);
    });
    fireEvent.click(
      document.querySelectorAll(".ant-select-dropdown .ant-select-item-option")[0]
    );
    // 输入 query + 检索
    fireEvent.change(screen.getByPlaceholderText(/搜索 query/), {
      target: { value: "RAG" },
    });
    const searchBtn = findBtnByText("检索");
    fireEvent.click(searchBtn!);
    // 等待结果 — title 用第一行, content_preview 用前 200 字
    // 文字同时出现在 title (span) + content_preview (div), 用 getAllByText
    // (getByText 在多匹配时会 throw).
    await waitFor(() => {
      expect(screen.getAllByText(/RAG 是检索增强生成/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/向量数据库选型/).length).toBeGreaterThan(0);
    });
    // 导入按钮 label 显示 "导入全部 2 条"
    expect(findBtnByText("导入全部2条")).toBeDefined();
  });

  it("search 出空结果时导入按钮 disabled", async () => {
    hoisted.knowledgeSearchMock.mockResolvedValue(kbResponse([]));
    render(
      <TestWrapper>
        <KBImportModal open onClose={vi.fn()} kbList={kbList} />
      </TestWrapper>
    );
    const selects = document.querySelectorAll(".ant-select-selector");
    fireEvent.mouseDown(selects[0]);
    await waitFor(() => {
      const opts = document.querySelectorAll(
        ".ant-select-dropdown .ant-select-item-option"
      );
      expect(opts.length).toBeGreaterThan(0);
    });
    fireEvent.click(
      document.querySelectorAll(".ant-select-dropdown .ant-select-item-option")[0]
    );
    fireEvent.change(screen.getByPlaceholderText(/搜索 query/), {
      target: { value: "空 query" },
    });
    const searchBtn = findBtnByText("检索");
    fireEvent.click(searchBtn!);
    await waitFor(() => expect(screen.getByText(/暂无检索结果/)).toBeInTheDocument());
    // 导入按钮 disabled (no results to import)
    const importBtn = findBtnByText("导入全部0条");
    expect(importBtn).toBeDefined();
    expect(importBtn!.hasAttribute("disabled")).toBe(true);
  });

  it("导入时调用 importFromKB 用 top_k=slider 值 (而非 selectedIds 数)", async () => {
    hoisted.knowledgeSearchMock.mockResolvedValue(
      kbResponse([
        { chunk_id: 201, content: "chunk A" },
        { chunk_id: 202, content: "chunk B" },
        { chunk_id: 203, content: "chunk C" },
      ])
    );
    hoisted.importFromKBMock.mockResolvedValue({
      imported: 3,
      skipped: 0,
      materials: [],
    });
    render(
      <TestWrapper>
        <KBImportModal open onClose={vi.fn()} kbList={kbList} />
      </TestWrapper>
    );
    // 选 KB + 检索
    const selects = document.querySelectorAll(".ant-select-selector");
    fireEvent.mouseDown(selects[0]);
    await waitFor(() => {
      const opts = document.querySelectorAll(
        ".ant-select-dropdown .ant-select-item-option"
      );
      expect(opts.length).toBeGreaterThan(0);
    });
    fireEvent.click(
      document.querySelectorAll(".ant-select-dropdown .ant-select-item-option")[0]
    );
    fireEvent.change(screen.getByPlaceholderText(/搜索 query/), {
      target: { value: "test" },
    });
    const searchBtn = findBtnByText("检索");
    fireEvent.click(searchBtn!);
    await waitFor(() => expect(screen.getByText(/导入全部 3 条/)).toBeInTheDocument());
    // 点导入 (不勾 checkbox)
    const importBtn = findBtnByText("导入全部3条");
    fireEvent.click(importBtn!);
    await waitFor(() => {
      expect(hoisted.importFromKBMock).toHaveBeenCalledWith({
        kb_id: 7,
        query: "test",
        top_k: 20, // 默认 slider 值 (未拖动)
      });
    });
  });
});
