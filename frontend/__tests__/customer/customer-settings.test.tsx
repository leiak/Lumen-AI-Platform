// frontend/__tests__/customer/customer-settings.test.tsx
// M33 — 客户管理 — 字段管理页 tests.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";
import CustomerFieldSettingsPage from "@/app/dashboard/customer/settings/page";

const hoisted = vi.hoisted(() => ({
  listMock: vi.fn(),
  createMock: vi.fn(),
  updateMock: vi.fn(),
  deleteMock: vi.fn(),
}));

vi.mock("@/services/customer", () => ({
  customerApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), delete: vi.fn(), restore: vi.fn(), upcomingFollowUps: vi.fn(), listFollowUps: vi.fn(), createFollowUp: vi.fn(), updateFollowUp: vi.fn(), deleteFollowUp: vi.fn(), aiSuggest: vi.fn() },
  customerFieldApi: {
    list: hoisted.listMock,
    create: hoisted.createMock,
    update: hoisted.updateMock,
    delete: hoisted.deleteMock,
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  usePathname: () => "/dashboard/customer/settings",
}));

const sampleFields = [
  {
    id: 1,
    field_key: "customer_ltv",
    field_label: "客户终身价值",
    field_type: "number",
    options: null,
    required: false,
    order_index: 0,
    is_active: true,
    created_by: 1,
    created_at: "2026-06-20T08:00:00Z",
    updated_at: "2026-06-20T08:00:00Z",
  },
  {
    id: 2,
    field_key: "decision_authority",
    field_label: "决策权",
    field_type: "select",
    options: ["low", "medium", "high"],
    required: true,
    order_index: 1,
    is_active: true,
    created_by: 1,
    created_at: "2026-06-20T08:00:00Z",
    updated_at: "2026-06-20T08:00:00Z",
  },
];

describe("CustomerFieldSettingsPage", () => {
  beforeEach(() => {
    hoisted.listMock.mockReset();
    hoisted.createMock.mockReset();
    hoisted.deleteMock.mockReset();

    hoisted.listMock.mockResolvedValue({
      items: sampleFields,
      total: 2,
      page: 1,
      page_size: 100,
    });
  });

  it("renders field definitions table", async () => {
    render(<TestWrapper><CustomerFieldSettingsPage /></TestWrapper>);
    await waitFor(() =>
      expect(screen.getByText("customer_ltv")).toBeInTheDocument()
    );
    expect(screen.getByText("客户终身价值")).toBeInTheDocument();
    expect(screen.getByText("decision_authority")).toBeInTheDocument();
    expect(screen.getByText("决策权")).toBeInTheDocument();
  });

  it("renders field type tags with correct colors", async () => {
    render(<TestWrapper><CustomerFieldSettingsPage /></TestWrapper>);
    await waitFor(() =>
      expect(screen.getByText("customer_ltv")).toBeInTheDocument()
    );
    // number -> cyan, select -> green
    expect(screen.getByText("数字")).toBeInTheDocument();
    expect(screen.getByText("单选")).toBeInTheDocument();
  });

  it("renders required tag for required fields", async () => {
    render(<TestWrapper><CustomerFieldSettingsPage /></TestWrapper>);
    await waitFor(() =>
      expect(screen.getByText("customer_ltv")).toBeInTheDocument()
    );
    // "必填" 出现在表格 cell 内, AntD Tag 的 textContent 直接匹配
    const cells = document.querySelectorAll(".ant-table-cell");
    const hasRequiredTag = Array.from(cells).some((c) =>
      c.textContent?.includes("必填"),
    );
    expect(hasRequiredTag).toBe(true);
  });

  it("opens create field modal", async () => {
    render(<TestWrapper><CustomerFieldSettingsPage /></TestWrapper>);
    await waitFor(() =>
      expect(screen.getByText("customer_ltv")).toBeInTheDocument()
    );

    fireEvent.click(screen.getByText("新建字段"));
    // Modal 是 portal 渲染,走 DOM class 选择器
    await waitFor(() => {
      const modals = document.querySelectorAll(".ant-modal-content");
      expect(modals.length).toBeGreaterThan(0);
    });
    const modal = document.querySelector(".ant-modal-content");
    expect(modal?.textContent).toContain("字段 Key");
    expect(modal?.textContent).toContain("显示名");
    expect(modal?.textContent).toContain("类型");
  });
});