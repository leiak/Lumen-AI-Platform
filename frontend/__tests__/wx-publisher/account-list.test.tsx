// frontend/__tests__/wx-publisher/account-list.test.tsx
// M32 — 公众号助手 — Account page tests.
// 3 cases: Table / AppSecret 一次性显示 Modal / Mock 切换.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";
import AccountsPage from "@/app/dashboard/wx-publisher/accounts/page";

const hoisted = vi.hoisted(() => ({
  listMock: vi.fn(),
  createMock: vi.fn(),
  updateMock: vi.fn(),
  verifyMock: vi.fn(),
  deleteMock: vi.fn(),
}));

vi.mock("@/services/wx-publisher", () => ({
  draftApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), delete: vi.fn(), addSection: vi.fn(), updateSection: vi.fn(), deleteSection: vi.fn(), reorderSections: vi.fn() },
  accountApi: {
    list: hoisted.listMock,
    get: vi.fn(),
    create: hoisted.createMock,
    update: hoisted.updateMock,
    verify: hoisted.verifyMock,
    delete: hoisted.deleteMock,
  },
  templateApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), delete: vi.fn(), thumbnailPath: (id: number) => `/x/${id}` },
  draftAiApi: { outline: vi.fn(), rewrite: vi.fn(), expand: vi.fn(), title: vi.fn(), render: vi.fn() },
  materialApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), delete: vi.fn(), importFromKB: vi.fn() },
  publishApi: { createPublish: vi.fn(), getPublish: vi.fn() },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useParams: () => ({ id: "1" }),
  usePathname: () => "/dashboard/wx-publisher/accounts",
}));

// accounts/page.tsx 通过 useQuery 拉 /auth/me 决定是否展示「永久删除」按钮。
// 默认非 superuser,符合现有 3 个测试的预期。purge 路径只在 admin + 显式触发
// 时才走到;这里 mock 留 placeholder 即可。
vi.mock("@/services/auth", () => ({
  authApi: {
    getMe: vi.fn().mockResolvedValue({
      data: { code: 200, data: { is_superuser: false } },
    }),
  },
}));

const sampleAccounts = [
  { id: 1, name: "科技早班车", app_id: "wxabcd1234567890abcd", app_secret_masked: "ab****cd", account_type: "subscription", is_mock: true, is_active: true, last_verified_at: null, created_at: "2026-06-17T08:00:00Z" },
];

describe("AccountsPage", () => {
  beforeEach(() => {
    hoisted.listMock.mockReset();
    hoisted.createMock.mockReset();
    hoisted.updateMock.mockReset();
    hoisted.verifyMock.mockReset();
    hoisted.deleteMock.mockReset();

    hoisted.listMock.mockResolvedValue({
      items: sampleAccounts,
      total: 1,
      page: 1,
      page_size: 100,
    });
  });

  it("renders account table", async () => {
    render(<TestWrapper><AccountsPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("科技早班车")).toBeInTheDocument());
    // 类型 tag
    expect(screen.getByText("订阅号")).toBeInTheDocument();
  });

  it("shows AppSecret reveal modal after create", async () => {
    hoisted.createMock.mockResolvedValue({
      id: 99,
      name: "新账号",
      app_id: "wxnewaccount12345678",
      app_secret_masked: "ne****78",
      account_type: "subscription",
      is_mock: true,
      is_active: true,
      last_verified_at: null,
      created_at: "2026-06-18T08:00:00Z",
    });

    render(<TestWrapper><AccountsPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("科技早班车")).toBeInTheDocument());

    // 打开新建 modal
    fireEvent.click(screen.getByText("新建账号"));
    await waitFor(() => expect(screen.getByText("新建公众号账号")).toBeInTheDocument());

    // 填表 — 走 form 内 input 直接按 placeholder 找.
    // 新建 modal 内 3 个 input 各自的 placeholder:
    //   - 账号名: "例: 科技早班车"
    //   - AppID:  "wx1234567890abcdef"
    //   - AppSecret: "仅创建时显示, 后续不再以明文展示"
    const nameInput = screen.getByPlaceholderText("例: 科技早班车") as HTMLInputElement;
    const appIdInput = screen.getByPlaceholderText("wx1234567890abcdef") as HTMLInputElement;
    const secretInput = screen.getByPlaceholderText(
      "仅创建时显示, 后续不再以明文展示"
    ) as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: "新账号" } });
    fireEvent.change(appIdInput, { target: { value: "wxnewaccount12345678" } });
    fireEvent.change(secretInput, {
      target: { value: "this_is_a_secret_at_least_20_chars_long_xx" },
    });

    // 提交 — modal footer OK 按钮 (okText="保存"). 取 modal 容器内的.
    await waitFor(() => {
      const saveButtons = document.querySelectorAll(
        ".ant-modal .ant-modal-footer .ant-btn-primary"
      );
      expect(saveButtons.length).toBeGreaterThan(0);
    });
    const okBtn = document.querySelector(
      ".ant-modal .ant-modal-footer .ant-btn-primary"
    ) as HTMLElement;
    fireEvent.click(okBtn);
    await waitFor(() => expect(screen.getByText("请保存 AppSecret")).toBeInTheDocument());
    expect(hoisted.createMock).toHaveBeenCalled();
  });

  it("calls update API when Mock toggle changes", async () => {
    hoisted.updateMock.mockResolvedValue(sampleAccounts[0]);
    render(<TestWrapper><AccountsPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("科技早班车")).toBeInTheDocument());

    // 找 Mock Switch — antd Switch with checkedChildren "Mock"
    const switches = document.querySelectorAll(".ant-switch");
    expect(switches.length).toBeGreaterThan(0);
    fireEvent.click(switches[0]);
    await waitFor(() => expect(hoisted.updateMock).toHaveBeenCalledWith(1, expect.objectContaining({ is_mock: expect.any(Boolean) })));
  });
});