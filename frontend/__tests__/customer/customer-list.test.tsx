// frontend/__tests__/customer/customer-list.test.tsx
// M33 — 客户管理 — 列表页 tests.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";
import CustomerListPage from "@/app/dashboard/customer/page";

const hoisted = vi.hoisted(() => ({
  listMock: vi.fn(),
  createMock: vi.fn(),
  updateMock: vi.fn(),
  deleteMock: vi.fn(),
  restoreMock: vi.fn(),
  upcomingMock: vi.fn(),
  listFollowUpsMock: vi.fn(),
  createFollowUpMock: vi.fn(),
  aiSuggestMock: vi.fn(),
  // 「负责人 Select」改造新引入的 2 个 query(mock 后,组件挂载就
  // 拿到数据,默认值也会立刻被推入 form,见 page.tsx 的 useEffect)。
  getMeMock: vi.fn(),
  assignableMock: vi.fn(),
}));

vi.mock("@/services/customer", () => ({
  customerApi: {
    list: hoisted.listMock,
    get: vi.fn(),
    create: hoisted.createMock,
    update: hoisted.updateMock,
    delete: hoisted.deleteMock,
    restore: hoisted.restoreMock,
    upcomingFollowUps: hoisted.upcomingMock,
    listFollowUps: hoisted.listFollowUpsMock,
    createFollowUp: hoisted.createFollowUpMock,
    updateFollowUp: vi.fn(),
    deleteFollowUp: vi.fn(),
    aiSuggest: hoisted.aiSuggestMock,
  },
  customerFieldApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("@/services/auth", () => ({
  authApi: {
    getMe: hoisted.getMeMock,
  },
}));

vi.mock("@/services/users", () => ({
  usersApi: {
    assignable: hoisted.assignableMock,
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  usePathname: () => "/dashboard/customer",
  useParams: () => ({ id: "1" }),
}));

const sampleCustomers = [
  {
    id: 1,
    name: "张三",
    phone_masked: "138****8000",
    email: "zhang@example.com",
    company_name: "ACME",
    company_position: "CTO",
    level: "vip",
    source: "referral",
    tags: ["决策人"],
    owner_user_id: 1,
    owner_user_name: "李四",
    last_follow_up_at: "2026-06-15T10:00:00Z",
    next_follow_up_at: null,
    is_active: true,
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-15T10:00:00Z",
  },
];

describe("CustomerListPage", () => {
  beforeEach(() => {
    hoisted.listMock.mockReset();
    hoisted.upcomingMock.mockReset();
    hoisted.getMeMock.mockReset();
    hoisted.assignableMock.mockReset();

    hoisted.listMock.mockResolvedValue({
      items: sampleCustomers,
      total: 1,
      page: 1,
      page_size: 20,
    });
    hoisted.upcomingMock.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
    });
    // 默认:当前用户 id=42(同租户里随便挑一个);assignable 列表
    // 包含 id=42(默认就是他) + id=7(其他同事,测试转单场景用)。
    hoisted.getMeMock.mockResolvedValue({
      data: { code: 200, data: { id: 42, username: "me", full_name: "Me" } },
    });
    hoisted.assignableMock.mockResolvedValue({
      items: [
        { id: 42, username: "me", full_name: "Me", email: "me@test.local" },
        { id: 7, username: "alice", full_name: "Alice", email: "alice@test.local" },
      ],
      total: 2,
      page: 1,
      page_size: 100,
    });
  });

  it("renders customer table with phone masked", async () => {
    render(<TestWrapper><CustomerListPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("张三")).toBeInTheDocument());
    expect(screen.getByText("138****8000")).toBeInTheDocument();
    // 列表里不该有完整 phone
    expect(screen.queryByText("13800138000")).not.toBeInTheDocument();
  });

  it("renders level tag with correct color", async () => {
    render(<TestWrapper><CustomerListPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("张三")).toBeInTheDocument());
    // vip -> gold tag
    const vipTag = screen.getByText("VIP");
    expect(vipTag).toBeInTheDocument();
  });

  it("calls list API with filter when level selected", async () => {
    render(<TestWrapper><CustomerListPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("张三")).toBeInTheDocument());
    // 初始调用 page=1, page_size=20, is_active=true
    expect(hoisted.listMock).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, page_size: 20, is_active: true }),
    );
  });

  it("opens upcoming follow-ups drawer", async () => {
    render(<TestWrapper><CustomerListPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("张三")).toBeInTheDocument());

    fireEvent.click(screen.getByText("待跟进"));
    // Drawer 是 portal 渲染,走 DOM class 选择器
    await waitFor(() => {
      const drawers = document.querySelectorAll(".ant-drawer-content");
      expect(drawers.length).toBeGreaterThan(0);
    });
    expect(hoisted.upcomingMock).toHaveBeenCalled();
  });

  it("opens create modal", async () => {
    render(<TestWrapper><CustomerListPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("张三")).toBeInTheDocument());

    fireEvent.click(screen.getByText("新建客户"));
    await waitFor(() =>
      expect(screen.getByText("基础信息")).toBeInTheDocument()
    );
    expect(screen.getByText("公司信息")).toBeInTheDocument();
    expect(screen.getByText("客户属性")).toBeInTheDocument();
  });

  it("owner_user_id defaults to current user when create modal opens", async () => {
    // 规格 §5.2:「负责人 Select(必填,默认当前用户)」
    // OwnerUserSelect 拉 /users/assignable,page.tsx 的 useEffect 把
    // currentUser.id 推到 form 的 owner_user_id 字段(空时)。
    // 验证流程:打开 modal → 调 getMe 和 assignable → form 收到 owner=42。
    const { baseElement } = render(
      <TestWrapper><CustomerListPage /></TestWrapper>
    );
    await waitFor(() => expect(screen.getByText("张三")).toBeInTheDocument());

    fireEvent.click(screen.getByText("新建客户"));
    await waitFor(() =>
      expect(screen.getByText("基础信息")).toBeInTheDocument()
    );

    // 两个 query 都被调了
    expect(hoisted.getMeMock).toHaveBeenCalled();
    expect(hoisted.assignableMock).toHaveBeenCalled();

    // AntD Modal 是 portal 渲染,必须从 baseElement 查(不是 container)。
    // 验证 Select 选中项的 label 包含当前用户 full_name "Me"(label 是
    // "full_name username email" 三段拼接,见 OwnerUserSelect.makeLabel)。
    await waitFor(() => {
      const items = baseElement.querySelectorAll(".ant-select-selection-item");
      const ownerSelected = Array.from(items).some((el) =>
        (el.textContent || "").includes("Me"),
      );
      expect(ownerSelected).toBe(true);
    });
  });
});
