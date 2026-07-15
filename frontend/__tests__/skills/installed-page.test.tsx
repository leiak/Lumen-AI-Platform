// frontend/__tests__/skills/installed-page.test.tsx
// Render-level tests for /dashboard/skills/installed: empty state, rows,
// uninstall happy path + error path.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { ConfigProvider, App, message } from "antd";

// Mock the services module so we don't hit the network.
const mockListInstalled = vi.fn();
const mockUninstallSkill = vi.fn();
const mockBatchUninstall = vi.fn();  // M20
vi.mock("@/services/skills", () => ({
  skillsApi: {
    listInstalled: (...args: any[]) => mockListInstalled(...args),
    uninstallSkill: (...args: any[]) => mockUninstallSkill(...args),
    batchUninstall: (...args: any[]) => mockBatchUninstall(...args),
  },
}));

// Mock next/navigation (useRouter).
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

import InstalledSkillsPage from "@/app/dashboard/skills/installed/page";
import type { InstalledSkill } from "@/services/skills";

const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>
    <App>{children}</App>
  </ConfigProvider>
);

const sampleSkill: InstalledSkill = {
  id: 3,
  skill_id: 11,
  name: "代码优化专家",
  category: "code",
  description: "优化代码",
  version: "1.0.0",
  rating: "4.8",
  downloads: 1200,
  is_installed: true,
};

// The page reads `res.data.data` (axios response -> PaginatedResponse envelope
// -> `data: T[]` field) plus `res.data.total` for the pager.
const buildListResponse = (list: InstalledSkill[], total: number) => ({
  data: {
    code: 200,
    message: "ok",
    data: list,
    total,
    page: 1,
    page_size: 50,
  },
});

describe("InstalledSkillsPage", () => {
  beforeEach(() => {
    mockListInstalled.mockReset();
    mockUninstallSkill.mockReset();
    mockBatchUninstall.mockReset();  // M20
    mockPush.mockReset();
    vi.spyOn(message, "success").mockImplementation((() => ({})) as any);
    vi.spyOn(message, "error").mockImplementation((() => ({})) as any);
  });

  it("renders the empty state when no skills are installed", async () => {
    mockListInstalled.mockResolvedValue(buildListResponse([], 0));
    render(<InstalledSkillsPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText(/尚未安装任何技能/)).toBeTruthy();
    });
  });

  it("renders rows when skills are returned", async () => {
    mockListInstalled.mockResolvedValue(buildListResponse([sampleSkill], 1));
    render(<InstalledSkillsPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("代码优化专家")).toBeTruthy();
    });
    expect(screen.getByText("code")).toBeTruthy();
  });

  it("calls uninstallSkill with the marketplace id and refetches on success", async () => {
    mockUninstallSkill.mockResolvedValue({
      data: { code: 200, message: "ok", data: null },
    });
    // After uninstall, the second call returns empty.
    mockListInstalled
      .mockResolvedValueOnce(buildListResponse([sampleSkill], 1))
      .mockResolvedValueOnce(buildListResponse([], 0))
      .mockResolvedValue(buildListResponse([], 0));

    render(<InstalledSkillsPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("代码优化专家")).toBeTruthy();
    });

    // Popconfirm: click the row's 卸载 button, then click 卸载 in the popover to confirm.
    // Use getAllByRole because once the popover opens, there are two "卸载" buttons
    // (the row trigger and the popover confirm). The trigger is the first one.
    const [triggerBtn] = screen.getAllByRole("button", { name: "卸载" });
    fireEvent.click(triggerBtn);
    const confirmBtn = (await screen.findAllByRole("button", { name: "卸载" }))[1];
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(mockUninstallSkill).toHaveBeenCalledWith(3); // marketplace_skill_id
    });
    await waitFor(
      () => {
        // M14 quirk: App.useApp() uses instance method, not static message,
        // so vi.spyOn(message, ...) doesn't capture. Assert toast text.
        expect(screen.getByText("已卸载 代码优化专家")).toBeTruthy();
      },
      { timeout: 3000 }
    );
    await waitFor(() => {
      expect(mockListInstalled).toHaveBeenCalledTimes(2);
    });
  });

  it("shows an error toast and does not refetch on uninstall failure", async () => {
    mockListInstalled.mockResolvedValue(buildListResponse([sampleSkill], 1));
    mockUninstallSkill.mockRejectedValue(new Error("boom"));

    render(<InstalledSkillsPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("代码优化专家")).toBeTruthy();
    });

    const [triggerBtn] = screen.getAllByRole("button", { name: "卸载" });
    fireEvent.click(triggerBtn);
    const confirmBtn = (await screen.findAllByRole("button", { name: "卸载" }))[1];
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(mockUninstallSkill).toHaveBeenCalled();
    });
    await waitFor(
      () => {
        // M14 quirk: assert toast text instead of vi.spyOn(message, ...)
        expect(screen.getByText("卸载失败")).toBeTruthy();
      },
      { timeout: 3000 }
    );
    // Should not have triggered a second fetch on failure.
    expect(mockListInstalled).toHaveBeenCalledTimes(1);
  });

  // ===== M20: server-side pagination + batch uninstall =====

  it("refetches when page changes (server-side pagination)", async () => {
    // 30 total -> 3 pages of 10. Page 1 returns 10 skills with unique names.
    const skills10 = Array.from({ length: 10 }, (_, i) => ({
      ...sampleSkill,
      id: i + 1,
      skill_id: (i + 1) * 10,
      name: `技能-${i + 1}`,
    }));
    mockListInstalled.mockResolvedValue(buildListResponse(skills10, 30));

    render(<InstalledSkillsPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("技能-1")).toBeTruthy();
    });

    // AntD pagination: click page 2. Page items have title attribute.
    const page2 = screen.getByTitle("2");
    fireEvent.click(page2);

    await waitFor(() => {
      const calls = mockListInstalled.mock.calls;
      expect(calls[calls.length - 1]).toEqual([2, 10]);
    });
  });

  it("renders the pageSize changer in pagination", async () => {
    mockListInstalled.mockResolvedValue(buildListResponse([sampleSkill], 1));
    render(<InstalledSkillsPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("代码优化专家")).toBeTruthy();
    });

    // AntD's pageSize changer is a Select. We just verify the element is in
    // the DOM; the actual dropdown interaction is handled by AntD itself.
    // (Clicking dropdown options in jsdom is brittle; manual UI smoke covers it.)
    const sizeChanger = document.querySelector(
      ".ant-pagination-options-size-changer"
    );
    expect(sizeChanger).toBeTruthy();
  });

  it("shows selected count tag and batch button when rows are selected", async () => {
    const skills3 = [
      { ...sampleSkill, id: 1, skill_id: 10 },
      { ...sampleSkill, id: 2, skill_id: 20, name: "测试工程师" },
      { ...sampleSkill, id: 3, skill_id: 30, name: "API 设计助手" },
    ];
    mockListInstalled.mockResolvedValue(buildListResponse(skills3, 3));
    render(<InstalledSkillsPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("代码优化专家")).toBeTruthy();
    });

    // Click 2 checkboxes in the table
    const checkboxes = document.querySelectorAll(
      ".ant-table-tbody .ant-checkbox-input"
    );
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);

    await waitFor(() => {
      expect(screen.getByTestId("selected-count")).toHaveTextContent("已选 2 项");
    });
    expect(screen.getByTestId("batch-uninstall-btn")).toBeTruthy();
  });

  it("calls batchUninstall with selected ids on confirm and refetches", async () => {
    const skills3 = [
      { ...sampleSkill, id: 3, skill_id: 11 },
      { ...sampleSkill, id: 5, skill_id: 22, name: "测试工程师" },
      { ...sampleSkill, id: 7, skill_id: 33, name: "API 设计助手" },
    ];
    mockListInstalled
      .mockResolvedValueOnce(buildListResponse(skills3, 3))
      .mockResolvedValueOnce(buildListResponse([skills3[2]], 1))
      .mockResolvedValue(buildListResponse([], 0));
    mockBatchUninstall.mockResolvedValue({
      data: {
        code: 200,
        message: "ok",
        data: { succeeded_count: 2, failed: [] },
      },
    });

    render(<InstalledSkillsPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("代码优化专家")).toBeTruthy();
    });

    // Select all 3
    const checkboxes = document.querySelectorAll(
      ".ant-table-tbody .ant-checkbox-input"
    );
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);
    fireEvent.click(checkboxes[2]);

    // Click batch uninstall button → opens Popconfirm
    const batchBtn = await screen.findByTestId("batch-uninstall-btn");
    fireEvent.click(batchBtn);

    // Click Popconfirm OK (the "卸载" button in the popover)
    const allUninstallBtns = screen.getAllByRole("button", { name: "卸载" });
    fireEvent.click(allUninstallBtns[allUninstallBtns.length - 1]);

    await waitFor(() => {
      expect(mockBatchUninstall).toHaveBeenCalledWith([11, 22, 33]);
    });
    await waitFor(() => {
      expect(mockListInstalled.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("shows warning toast on partial batch failure", async () => {
    const skills2 = [
      { ...sampleSkill, id: 3, skill_id: 11 },
      { ...sampleSkill, id: 5, skill_id: 22, name: "测试工程师" },
    ];
    mockListInstalled.mockResolvedValue(buildListResponse(skills2, 2));
    mockBatchUninstall.mockResolvedValue({
      data: {
        code: 200,
        message: "ok",
        data: { succeeded_count: 1, failed: [{ id: 22, reason: "not installed" }] },
      },
    });

    render(<InstalledSkillsPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("代码优化专家")).toBeTruthy();
    });

    const checkboxes = document.querySelectorAll(
      ".ant-table-tbody .ant-checkbox-input"
    );
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);

    const batchBtn = await screen.findByTestId("batch-uninstall-btn");
    fireEvent.click(batchBtn);
    const allUninstallBtns = screen.getAllByRole("button", { name: "卸载" });
    fireEvent.click(allUninstallBtns[allUninstallBtns.length - 1]);

    // Wait for the warning toast text to appear
    await waitFor(
      () => {
        expect(screen.getByText(/已卸载 1 项.*1 项失败/)).toBeTruthy();
      },
      { timeout: 3000 }
    );
  });

  it("flips to previous page when current page is emptied by batch uninstall", async () => {
    // Initial page 1: 10 skills, total 11. Page 2: 1 skill.
    const skills10 = Array.from({ length: 10 }, (_, i) => ({
      ...sampleSkill,
      id: i + 1,
      skill_id: (i + 1) * 10,
      name: `技能-${i + 1}`,
    }));
    const skills1 = [{ ...sampleSkill, id: 11, skill_id: 111, name: "技能-11" }];
    mockListInstalled
      .mockResolvedValueOnce(buildListResponse(skills10, 11))
      .mockResolvedValueOnce(buildListResponse(skills1, 1));
    mockBatchUninstall.mockResolvedValue({
      data: { code: 200, message: "ok", data: { succeeded_count: 1, failed: [] } },
    });

    render(<InstalledSkillsPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("技能-1")).toBeTruthy();
    });

    // Navigate to page 2
    const page2 = screen.getByTitle("2");
    fireEvent.click(page2);

    await waitFor(() => {
      const calls = mockListInstalled.mock.calls;
      expect(calls[calls.length - 1]).toEqual([2, 10]);
    });

    // Select the only row on page 2
    const checkboxes = document.querySelectorAll(
      ".ant-table-tbody .ant-checkbox-input"
    );
    fireEvent.click(checkboxes[0]);

    // Click batch uninstall
    const batchBtn = await screen.findByTestId("batch-uninstall-btn");
    fireEvent.click(batchBtn);
    const allUninstallBtns = screen.getAllByRole("button", { name: "卸载" });
    fireEvent.click(allUninstallBtns[allUninstallBtns.length - 1]);

    // After page 2 empty, component should call setCurrentPage(1) → useEffect refetches (1, 10)
    await waitFor(() => {
      const calls = mockListInstalled.mock.calls;
      // Last call should be (1, 10) — either from explicit setCurrentPage(1) trigger,
      // or from the refetch after setCurrentPage(1) was called.
      const lastCall = calls[calls.length - 1];
      expect([1, 10]).toEqual([lastCall[0], lastCall[1]]);
    });
  });

  it("shows error toast on batch uninstall network failure", async () => {
    const skills2 = [
      { ...sampleSkill, id: 3, skill_id: 11 },
      { ...sampleSkill, id: 5, skill_id: 22, name: "测试工程师" },
    ];
    mockListInstalled.mockResolvedValue(buildListResponse(skills2, 2));
    mockBatchUninstall.mockRejectedValue(new Error("network down"));

    render(<InstalledSkillsPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("代码优化专家")).toBeTruthy();
    });

    const checkboxes = document.querySelectorAll(
      ".ant-table-tbody .ant-checkbox-input"
    );
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);

    const batchBtn = await screen.findByTestId("batch-uninstall-btn");
    fireEvent.click(batchBtn);
    const allUninstallBtns = screen.getAllByRole("button", { name: "卸载" });
    fireEvent.click(allUninstallBtns[allUninstallBtns.length - 1]);

    await waitFor(
      () => {
        expect(screen.getByText("批量卸载失败")).toBeTruthy();
      },
      { timeout: 3000 }
    );
  });
});
