// frontend/__tests__/eval/dataset-detail.test.tsx
// M37.1 — /dashboard/eval/datasets/[id] detail page tests (6 cases).
//
// Covers:
//   1. loading 时渲染 Skeleton
//   2. 数据回来后渲染 dataset info card(name + KB + items count + builtin tag)
//   3. 渲染 items table(query + category + difficulty Tag)
//   4. 点「加 item」打开 ItemFormModal
//   5. 提交 ItemFormModal 调 addItem
//   6. 点「批量导入」打开 BulkImportModal

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";

const mockGetDataset = vi.fn();
const mockListItems = vi.fn();
const mockAddItem = vi.fn();
const mockDeleteItem = vi.fn();
const mockDeleteDataset = vi.fn();

vi.mock("@/services/eval_dataset", () => ({
  getDataset: (...args: any[]) => mockGetDataset(...args),
  listItems: (...args: any[]) => mockListItems(...args),
  addItem: (...args: any[]) => mockAddItem(...args),
  deleteItem: (...args: any[]) => mockDeleteItem(...args),
  deleteDataset: (...args: any[]) => mockDeleteDataset(...args),
}));

const mockPush = vi.fn();
const mockUseParams = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useParams: (...args: any[]) => mockUseParams(...args),
}));

import EvalDatasetDetailPage from "@/app/dashboard/eval/datasets/[id]/page";

beforeEach(() => {
  window.localStorage.setItem("access_token", "test-token");
  mockGetDataset.mockReset();
  mockListItems.mockReset();
  mockAddItem.mockReset();
  mockDeleteItem.mockReset();
  mockDeleteDataset.mockReset();
  mockPush.mockReset();
  mockUseParams.mockReset();
  mockUseParams.mockReturnValue({ id: "42" });
  // 默认 dataset + 空 items
  mockGetDataset.mockResolvedValue({
    id: 42,
    kb_id: 7,
    tenant_id: null,
    name: "demo_baseline",
    source: "manual",
    is_active: 1,
    item_count: 2,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    description: "a demo baseline dataset",
    created_by: null,
  });
  mockListItems.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 });
  mockAddItem.mockResolvedValue({ id: 100, dataset_id: 42, query: "x" });
});

describe("EvalDatasetDetailPage", () => {
  it("renders loading skeleton initially", async () => {
    // 让 getDataset 永不 resolve → 触发 Skeleton
    mockGetDataset.mockImplementation(() => new Promise(() => {}));
    render(
      <TestWrapper>
        <EvalDatasetDetailPage />
      </TestWrapper>
    );
    // Skeleton 的 ant-skeleton 类存在即说明在加载态
    expect(document.querySelector(".ant-skeleton")).toBeInTheDocument();
  });

  it("renders dataset info card with name + KB tag + builtin tag", async () => {
    render(
      <TestWrapper>
        <EvalDatasetDetailPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockGetDataset).toHaveBeenCalled());
    expect(await screen.findByText("demo_baseline")).toBeInTheDocument();
    // builtin tag
    expect(screen.getByText("builtin")).toBeInTheDocument();
    // KB tag
    expect(screen.getByText("#7")).toBeInTheDocument();
    // Items 数
    expect(screen.getByText("2")).toBeInTheDocument();
    // description
    expect(screen.getByText("a demo baseline dataset")).toBeInTheDocument();
  });

  it("renders items table with category + difficulty Tags", async () => {
    mockListItems.mockResolvedValue({
      items: [
        {
          id: 1,
          dataset_id: 42,
          query: "如何申请退货?",
          expected_doc_ids: [12, 18, 99],
          expected_answer: "7 天内联系客服",
          answer_keywords: null,
          category: "factual",
          difficulty: "easy",
          notes: null,
          created_at: "2026-08-01T00:00:00Z",
        },
        {
          id: 2,
          dataset_id: 42,
          query: "为什么订单状态没更新?",
          expected_doc_ids: [],
          expected_answer: null,
          answer_keywords: null,
          category: "reasoning",
          difficulty: "hard",
          notes: null,
          created_at: "2026-08-01T00:00:00Z",
        },
      ],
      total: 2,
      page: 1,
      page_size: 200,
    });
    render(
      <TestWrapper>
        <EvalDatasetDetailPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListItems).toHaveBeenCalled());
    // Items 标题
    expect(await screen.findByText(/Items \(2\)/)).toBeInTheDocument();
    // query 文本
    expect(screen.getByText("如何申请退货?")).toBeInTheDocument();
    expect(screen.getByText("为什么订单状态没更新?")).toBeInTheDocument();
    // category Tags
    expect(screen.getByText("事实")).toBeInTheDocument();
    expect(screen.getByText("推理")).toBeInTheDocument();
    // difficulty Tags
    expect(screen.getByText("简单")).toBeInTheDocument();
    expect(screen.getByText("困难")).toBeInTheDocument();
    // expected_doc_ids(前 3 个 + 越界 +N 显示 —— 这里只有 3 个,所以无 +N)
    expect(screen.getByText("#12")).toBeInTheDocument();
    expect(screen.getByText("#18")).toBeInTheDocument();
    expect(screen.getByText("#99")).toBeInTheDocument();
  });

  it("clicking 加 item opens ItemFormModal", async () => {
    render(
      <TestWrapper>
        <EvalDatasetDetailPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockGetDataset).toHaveBeenCalled());
    fireEvent.click(await screen.findByRole("button", { name: /加 item/ }));
    expect(await screen.findByText("新增 item")).toBeInTheDocument();
    // 期望文档 ID 是表单特有 label(列表表头没有),用此确认 modal 真的开了
    expect(screen.getByText("期望文档 ID")).toBeInTheDocument();
  });

  it("submitting ItemFormModal calls addItem", async () => {
    render(
      <TestWrapper>
        <EvalDatasetDetailPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockGetDataset).toHaveBeenCalled());
    fireEvent.click(await screen.findByRole("button", { name: /加 item/ }));

    // 填 query
    const queryInput = await screen.findByPlaceholderText(/如何申请退货/);
    fireEvent.change(queryInput, { target: { value: "test query?" } });
    fireEvent.click(screen.getByRole("button", { name: /保存/ }));

    await waitFor(() => expect(mockAddItem).toHaveBeenCalled());
    expect(mockAddItem).toHaveBeenCalledWith(42, expect.objectContaining({ query: "test query?" }));
  });

  it("clicking 批量导入 opens BulkImportModal with drop zone", async () => {
    render(
      <TestWrapper>
        <EvalDatasetDetailPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockGetDataset).toHaveBeenCalled());
    fireEvent.click(await screen.findByRole("button", { name: /批量导入/ }));
    // BulkImportModal 标题里有 dataset id
    expect(await screen.findByText(/批量导入 items — dataset #42/)).toBeInTheDocument();
    // 拖拽上传区
    expect(screen.getByText(/点击或拖拽 \.json 文件到此区域/)).toBeInTheDocument();
  });
});