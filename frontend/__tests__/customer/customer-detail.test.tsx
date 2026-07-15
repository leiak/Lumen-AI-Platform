// frontend/__tests__/customer/customer-detail.test.tsx
// M33 — 客户管理 — 详情页 tests.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";
import CustomerDetailPage from "@/app/dashboard/customer/[id]/page";

const hoisted = vi.hoisted(() => ({
  getMock: vi.fn(),
  listFollowUpsMock: vi.fn(),
  createFollowUpMock: vi.fn(),
  updateFollowUpMock: vi.fn(),
  deleteFollowUpMock: vi.fn(),
  aiSuggestMock: vi.fn(),
}));

vi.mock("@/services/customer", () => ({
  customerApi: {
    list: vi.fn(),
    get: hoisted.getMock,
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    restore: vi.fn(),
    upcomingFollowUps: vi.fn(),
    listFollowUps: hoisted.listFollowUpsMock,
    createFollowUp: hoisted.createFollowUpMock,
    updateFollowUp: hoisted.updateFollowUpMock,
    deleteFollowUp: hoisted.deleteFollowUpMock,
    aiSuggest: hoisted.aiSuggestMock,
  },
  customerFieldApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useParams: () => ({ id: "1" }),
  usePathname: () => "/dashboard/customer/1",
}));

const sampleCustomer = {
  id: 1,
  name: "张三",
  phone: "13800138000",
  email: "zhang@example.com",
  wechat: "zhang_san",
  avatar_url: null,
  gender: "M",
  birthday: "1990-05-15",
  address: "北京",
  company_name: "ACME",
  company_position: "CTO",
  industry: "IT",
  company_size: "51-200",
  company_website: "https://acme.com",
  level: "vip",
  source: "referral",
  tags: ["决策人"],
  custom_fields: { ltv: 50000 },
  custom_fields_schema_resolved: [
    { key: "ltv", label: "LTV", type: "number", value: 50000, required: false, options: null },
  ],
  remark: "VIP 客户",
  owner_user_id: 1,
  owner_user_name: "李四",
  created_by: 1,
  last_follow_up_at: "2026-06-15T10:00:00Z",
  next_follow_up_at: "2026-06-25T10:00:00Z",
  follow_ups_count: 2,
  is_active: true,
  created_at: "2026-06-01T00:00:00Z",
  updated_at: "2026-06-15T10:00:00Z",
};

const sampleFollowUps = [
  {
    id: 100,
    customer_id: 1,
    follow_up_type: "phone",
    content: "初次沟通,客户对 X 产品有兴趣",
    next_step: "发送产品 demo",
    next_follow_up_at: null,
    ai_suggested: false,
    user_id: 1,
    user_name: "李四",
    created_at: "2026-06-15T10:00:00Z",
  },
  {
    id: 99,
    customer_id: 1,
    follow_up_type: "wechat",
    content: "AI 智能建议创建的话术",
    next_step: null,
    next_follow_up_at: null,
    ai_suggested: true,
    user_id: 1,
    user_name: "李四",
    created_at: "2026-06-10T09:00:00Z",
  },
];

describe("CustomerDetailPage", () => {
  beforeEach(() => {
    hoisted.getMock.mockReset();
    hoisted.listFollowUpsMock.mockReset();
    hoisted.createFollowUpMock.mockReset();
    hoisted.deleteFollowUpMock.mockReset();
    hoisted.aiSuggestMock.mockReset();

    hoisted.getMock.mockResolvedValue(sampleCustomer);
    hoisted.listFollowUpsMock.mockResolvedValue({
      items: sampleFollowUps,
      total: 2,
      page: 1,
      page_size: 100,
    });
  });

  it("renders customer header with full phone and vip tag", async () => {
    render(<TestWrapper><CustomerDetailPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("张三")).toBeInTheDocument());
    expect(screen.getByText("13800138000")).toBeInTheDocument(); // 详情手机号完整
    expect(screen.getAllByText("VIP").length).toBeGreaterThan(0);
  });

  it("renders basic info and company info cards", async () => {
    render(<TestWrapper><CustomerDetailPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("张三")).toBeInTheDocument());
    expect(screen.getByText("基础信息")).toBeInTheDocument();
    expect(screen.getByText("公司信息")).toBeInTheDocument();
    expect(screen.getByText("ACME")).toBeInTheDocument();
    expect(screen.getByText("CTO")).toBeInTheDocument();
  });

  it("renders follow-up timeline with ai suggested tag", async () => {
    render(<TestWrapper><CustomerDetailPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("张三")).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getByText("初次沟通,客户对 X 产品有兴趣")).toBeInTheDocument()
    );
    // AI 建议的跟进应该显示 AI 建议 Tag
    expect(screen.getByText("AI 建议")).toBeInTheDocument();
  });

  it("renders custom fields with resolved labels", async () => {
    render(<TestWrapper><CustomerDetailPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("张三")).toBeInTheDocument());
    expect(screen.getByText("LTV")).toBeInTheDocument();
    expect(screen.getByText("50000")).toBeInTheDocument();
  });

  it("opens create follow-up modal", async () => {
    render(<TestWrapper><CustomerDetailPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("张三")).toBeInTheDocument());

    fireEvent.click(screen.getByText("新增跟进"));
    // Modal 是 portal 渲染,走 DOM class 选择器
    await waitFor(() => {
      const modals = document.querySelectorAll(".ant-modal-content");
      expect(modals.length).toBeGreaterThan(0);
    });
    // 跟进类型 + 跟进内容 label 应在 modal 内
    const modal = document.querySelector(".ant-modal-content");
    expect(modal?.textContent).toContain("跟进内容");
    expect(modal?.textContent).toContain("跟进类型");
  });
});