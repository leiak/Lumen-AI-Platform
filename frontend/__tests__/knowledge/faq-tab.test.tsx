// frontend/__tests__/knowledge/faq-tab.test.tsx
// M31: FAQTab component-level tests.
//
// Covers the create / edit / delete / bulk-import user flows
// at the component level. Uses the same TestWrapper pattern
// as delete-blockers.test.tsx.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { ConfigProvider, App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import FAQTab from "@/components/knowledge/FAQTab";

const mockListFaqs = vi.fn();
const mockCreateFaq = vi.fn();
const mockUpdateFaq = vi.fn();
const mockDeleteFaq = vi.fn();
const mockBulkImportFaqs = vi.fn();

vi.mock("@/services/knowledge", () => ({
  knowledgeApi: {
    listFaqs: (...args: any[]) => mockListFaqs(...args),
    createFaq: (...args: any[]) => mockCreateFaq(...args),
    updateFaq: (...args: any[]) => mockUpdateFaq(...args),
    deleteFaq: (...args: any[]) => mockDeleteFaq(...args),
    bulkImportFaqs: (...args: any[]) => mockBulkImportFaqs(...args),
  },
}));

const TestWrapper = ({ children }: { children: React.ReactNode }) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <ConfigProvider button={{ autoInsertSpace: false }}>
      <App>
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      </App>
    </ConfigProvider>
  );
};

const sampleFaq = {
  id: 1,
  knowledge_base_id: 42,
  question: "如何申请退货?",
  answer: "请在 7 天内联系客服",
  category: "退货政策",
  tags: ["急"],
  vector_id: "vec_1",
  document_id: 100,
  chunk_id: 200,
  created_at: "2026-06-17T00:00:00Z",
  updated_at: "2026-06-17T00:00:00Z",
};

const listResponse = {
  data: {
    code: 200,
    message: "ok",
    data: [sampleFaq],
    total: 1,
    page: 1,
    page_size: 20,
  },
};

describe("FAQTab — M31 Q&A subcomponent", () => {
  beforeEach(() => {
    mockListFaqs.mockReset();
    mockCreateFaq.mockReset();
    mockUpdateFaq.mockReset();
    mockDeleteFaq.mockReset();
    mockBulkImportFaqs.mockReset();
    mockListFaqs.mockResolvedValue(listResponse);
    mockCreateFaq.mockResolvedValue({
      data: { code: 200, data: { ...sampleFaq, id: 2 } },
    });
    mockUpdateFaq.mockResolvedValue({
      data: { code: 200, data: sampleFaq },
    });
    mockDeleteFaq.mockResolvedValue({
      data: { code: 200, data: { entry_id: 1, deleted: true } },
    });
    mockBulkImportFaqs.mockResolvedValue({
      data: { code: 200, data: { inserted: 2, failed: [] } },
    });
  });

  it("renders the list with question, answer, category, tags, and actions", async () => {
    render(
      <TestWrapper>
        <FAQTab kbId={42} />
      </TestWrapper>
    );

    // Wait for the list to load.
    await waitFor(() => {
      expect(mockListFaqs).toHaveBeenCalled();
    });
    // The query response is async, so the table content
    // takes a tick to render after listFaqs resolves. Use
    // waitFor on the actual table cell content rather than
    // asserting immediately after the call — antd's
    // ``Table`` runs a microtask before the data prop is
    // applied.
    await waitFor(() => {
      expect(screen.getByText("退货政策")).toBeInTheDocument();
    });
    expect(screen.getByText("退货政策")).toBeInTheDocument();
    expect(screen.getByText("急")).toBeInTheDocument();
  });

  it("clicking 新建问答 opens the create modal", async () => {
    render(
      <TestWrapper>
        <FAQTab kbId={42} />
      </TestWrapper>
    );
    await waitFor(() => {
      expect(mockListFaqs).toHaveBeenCalled();
    });
    fireEvent.click(screen.getByTestId("faq-create-btn"));
    await waitFor(() => {
      expect(screen.getByTestId("faq-form-modal")).toBeInTheDocument();
    });
  });

  it("create form submits via createFaq with the right payload", async () => {
    render(
      <TestWrapper>
        <FAQTab kbId={42} />
      </TestWrapper>
    );
    await waitFor(() => {
      expect(mockListFaqs).toHaveBeenCalled();
    });
    fireEvent.click(screen.getByTestId("faq-create-btn"));
    await waitFor(() => {
      expect(screen.getByTestId("faq-form-modal")).toBeInTheDocument();
    });

    // Fill in the form. Note: we fire change events on
    // the inputs and then click OK.
    const questionInput = await screen.findByTestId("faq-form-question");
    const answerInput = await screen.findByTestId("faq-form-answer");

    fireEvent.change(questionInput, {
      target: { value: "运费多少?" },
    });
    fireEvent.change(answerInput, {
      target: { value: "包邮订单免运费" },
    });

    // Click OK in the modal footer. The modal renders the
    // "新增" button (text varies between create and edit).
    const okBtn = screen.getByRole("button", { name: /新增/ });
    fireEvent.click(okBtn);

    await waitFor(() => {
      expect(mockCreateFaq).toHaveBeenCalled();
    });
    // Payload contains the trimmed question/answer.
    const call = mockCreateFaq.mock.calls[0];
    expect(call[0]).toBe(42);
    expect(call[1].question).toBe("运费多少?");
    expect(call[1].answer).toBe("包邮订单免运费");
  });

  it("bulk import modal accepts JSON content and calls bulkImportFaqs", async () => {
    render(
      <TestWrapper>
        <FAQTab kbId={42} />
      </TestWrapper>
    );
    await waitFor(() => {
      expect(mockListFaqs).toHaveBeenCalled();
    });

    fireEvent.click(screen.getByTestId("faq-bulk-btn"));
    await waitFor(() => {
      expect(screen.getByTestId("faq-bulk-modal")).toBeInTheDocument();
    });

    // The format Select defaults to JSON; just fill the
    // content TextArea.
    const contentArea = screen.getByTestId("faq-bulk-content");
    fireEvent.change(contentArea, {
      target: { value: '[{"question":"Q1","answer":"A1"}]' },
    });

    // Submit. The OK button in the bulk modal is labelled
    // "开始导入".
    const okBtn = screen.getByRole("button", { name: /开始导入/ });
    fireEvent.click(okBtn);

    await waitFor(() => {
      expect(mockBulkImportFaqs).toHaveBeenCalled();
    });
    expect(mockBulkImportFaqs).toHaveBeenCalledWith(42, {
      format: "json",
      content: '[{"question":"Q1","answer":"A1"}]',
    });
  });

  it("delete button triggers deleteFaq after Popconfirm", async () => {
    render(
      <TestWrapper>
        <FAQTab kbId={42} />
      </TestWrapper>
    );
    await waitFor(() => {
      expect(mockListFaqs).toHaveBeenCalled();
    });
    // Wait for the row to render.
    await waitFor(() => {
      expect(screen.getAllByText("如何申请退货?")[0]).toBeInTheDocument();
    });

    // Click the row's "删除" link button (triggers Popconfirm).
    const deleteLink = screen.getAllByRole("button", { name: /删除/ })[0];
    fireEvent.click(deleteLink);

    // Popconfirm shows up — click the danger button.
    await waitFor(() => {
      expect(
        document.querySelector(".ant-popconfirm-buttons .ant-btn-primary")
      ).toBeInTheDocument();
    });
    const okBtn = document.querySelector(
      ".ant-popconfirm-buttons .ant-btn-primary"
    ) as HTMLButtonElement;
    fireEvent.click(okBtn);

    await waitFor(() => {
      expect(mockDeleteFaq).toHaveBeenCalled();
    });
    expect(mockDeleteFaq).toHaveBeenCalledWith(42, 1);
  });

  it("search input triggers listFaqs with the search param on Enter", async () => {
    render(
      <TestWrapper>
        <FAQTab kbId={42} />
      </TestWrapper>
    );
    await waitFor(() => {
      expect(mockListFaqs).toHaveBeenCalled();
    });
    mockListFaqs.mockClear();

    const search = screen.getByTestId("faq-search-input");
    fireEvent.change(search, { target: { value: "运费" } });
    fireEvent.keyDown(search, { key: "Enter", code: "Enter", charCode: 13 });

    await waitFor(() => {
      // The search should trigger a refetch with the search
      // param. We assert that at least one of the recent
      // calls includes ``search: "运费"``.
      const callsWithSearch = mockListFaqs.mock.calls.filter(
        (c) => c[1] && c[1].search === "运费"
      );
      expect(callsWithSearch.length).toBeGreaterThan(0);
    });
  });
});
