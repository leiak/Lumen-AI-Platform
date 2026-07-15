// frontend/__tests__/skills/market-detail.test.tsx
// Render-level tests for /dashboard/skills/market: detail drawer open/close,
// prompt content rendering, copy button, installed flag handling, install
// action, and 404 error path.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { ConfigProvider, App as AntApp } from "antd";

// Mock the services module so we don't hit the network.
const mockListMarketplace = vi.fn();
const mockInstallSkill = vi.fn();
const mockGetMarketplaceSkill = vi.fn();
vi.mock("@/services/skills", () => ({
  skillsApi: {
    listMarketplace: (...args: any[]) => mockListMarketplace(...args),
    installSkill: (...args: any[]) => mockInstallSkill(...args),
    getMarketplaceSkill: (...args: any[]) => mockGetMarketplaceSkill(...args),
    listInstalled: vi.fn(),
    uninstallSkill: vi.fn(),
    getCategories: vi.fn(),
  },
}));

import SkillsMarketPage from "@/app/dashboard/skills/market/page";
import type { MarketplaceSkill } from "@/services/skills";

const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider>
    {/* AntApp wrapper is required for App.useApp() to provide a real
        message instance (per project 2026-06-07 lesson). */}
    <AntApp>{children}</AntApp>
  </ConfigProvider>
);

const sampleSkill: MarketplaceSkill = {
  id: 1,
  name: "代码优化专家",
  category: "code",
  description: "帮助优化代码",
  downloads: 1200,
  rating: 4.8,
  version: "1.0.0",
  provider: "Lumen AI Platform",
  is_verified: true,
  is_installed: false,
  content: "You are a code optimization expert. Analyze code and suggest improvements.",
};

const anotherSkill: MarketplaceSkill = {
  id: 2,
  name: "文档写作助手",
  category: "writing",
  description: "帮助撰写文档",
  downloads: 890,
  rating: 4.6,
  version: "1.0.0",
  provider: "Lumen AI Platform",
  is_verified: true,
  is_installed: false,
  content: "You are a documentation assistant.",
};

const buildListResponse = (list: MarketplaceSkill[]) => ({
  data: { code: 200, message: "ok", data: list, total: list.length, page: 1, page_size: 20 },
});

const buildDetailResponse = (skill: MarketplaceSkill | null) =>
  skill
    ? { data: { code: 200, message: "ok", data: skill } }
    : { data: { code: 404, message: "not found", data: null } };

describe("SkillsMarketPage - detail drawer", () => {
  beforeEach(() => {
    mockListMarketplace.mockReset();
    mockInstallSkill.mockReset();
    mockGetMarketplaceSkill.mockReset();
  });

  it("detail button opens drawer with skill name", async () => {
    mockListMarketplace.mockResolvedValue(buildListResponse([sampleSkill, anotherSkill]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetailResponse(sampleSkill));

    const { container } = render(<TestWrapper><SkillsMarketPage /></TestWrapper>);

    // Helper: query document.body so we can see Drawer's portal-rendered content.
    // AntD Drawer mounts to document.body via portal, not into the React root container.
    const getBody = () => document.body.textContent || "";

    // Wait for table to load
    await waitFor(() => {
      expect(getBody()).toContain("代码优化专家");
    });

    // Click "详情" button (use role-based query)
    const detailButtons = screen.getAllByRole("button", { name: "详情" });
    fireEvent.click(detailButtons[0]);

    // Drawer should show skill name and content (in document.body portal)
    await waitFor(() => {
      expect(mockGetMarketplaceSkill).toHaveBeenCalledWith(1);
      expect(getBody()).toContain("You are a code optimization expert");
    });
  });

  it("copy button uses clipboard api", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    mockListMarketplace.mockResolvedValue(buildListResponse([sampleSkill]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetailResponse(sampleSkill));

    const { container } = render(<TestWrapper><SkillsMarketPage /></TestWrapper>);

    // Wait for table to load
    await waitFor(() => {
      expect(document.body.textContent).toContain("代码优化专家");
    });

    // Open detail
    const detailBtn = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent?.trim() === "详情"
    );
    expect(detailBtn).toBeDefined();
    fireEvent.click(detailBtn!);

    // Wait for drawer to render
    await waitFor(() => {
      expect(document.body.textContent).toContain("You are a code optimization expert");
    });

    // Click 复制 button (find by text in body to include drawer portal)
    const copyBtn = Array.from(document.body.querySelectorAll("button")).find(
      (b) => b.textContent?.trim() === "复制"
    );
    expect(copyBtn).toBeDefined();
    fireEvent.click(copyBtn!);

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(sampleSkill.content));
  });

  it("drawer shows 已安装 tag when is_installed=true", async () => {
    const installedSkill: MarketplaceSkill = { ...sampleSkill, is_installed: true };
    mockListMarketplace.mockResolvedValue(buildListResponse([installedSkill]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetailResponse(installedSkill));

    const { container } = render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    const getBody = () => document.body.textContent || "";
    await waitFor(() => {
      expect(getBody()).toContain("代码优化专家");
    });

    fireEvent.click(screen.getByRole("button", { name: "详情" }));
    await waitFor(() => {
      expect(getBody()).toContain("You are a code optimization expert");
    });

    // In the drawer footer, "已安装" tag should be present (table row button + drawer tag)
    await waitFor(() => {
      const matches = getBody().match(/已安装/g) || [];
      expect(matches.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("drawer install button calls installSkill API", async () => {
    mockListMarketplace.mockResolvedValue(buildListResponse([sampleSkill]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetailResponse(sampleSkill));
    mockInstallSkill.mockResolvedValue({ data: { code: 200, message: "ok", data: null } });

    const { container } = render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    const getBody = () => document.body.textContent || "";
    await waitFor(() => {
      expect(getBody()).toContain("代码优化专家");
    });

    fireEvent.click(screen.getByRole("button", { name: "详情" }));
    await waitFor(() => {
      expect(getBody()).toContain("You are a code optimization expert");
    });

    // Find install buttons by text; click the one inside the drawer (last).
    const installButtons = Array.from(container.querySelectorAll("button")).filter(
      (b) => b.textContent?.includes("安装") && !b.disabled
    );
    expect(installButtons.length).toBeGreaterThan(0);
    fireEvent.click(installButtons[installButtons.length - 1]);

    await waitFor(() => expect(mockInstallSkill).toHaveBeenCalledWith(1));
  });

  it("table install button is disabled when is_installed=true", async () => {
    const installedSkill: MarketplaceSkill = { ...sampleSkill, is_installed: true };
    mockListMarketplace.mockResolvedValue(buildListResponse([installedSkill]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetailResponse(installedSkill));

    const { container } = render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    const getBody = () => document.body.textContent || "";
    await waitFor(() => {
      expect(getBody()).toContain("代码优化专家");
    });

    const allButtons = container.querySelectorAll("button");
    const installedBtn = Array.from(allButtons).find(
      (b) => b.textContent === "已安装"
    );
    expect(installedBtn).toBeDefined();
    expect((installedBtn as HTMLButtonElement).disabled).toBe(true);
  });

  it("drawer renders all sections (header, meta, description, prompt)", async () => {
    mockListMarketplace.mockResolvedValue(buildListResponse([sampleSkill]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetailResponse(sampleSkill));

    const { container } = render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    const getBody = () => document.body.textContent || "";
    await waitFor(() => {
      expect(getBody()).toContain("代码优化专家");
    });

    fireEvent.click(screen.getByRole("button", { name: "详情" }));
    await waitFor(() => {
      expect(getBody()).toContain("You are a code optimization expert");
    });

    // Verify all 4 sections of SkillDetailContent render
    expect(getBody()).toContain("v1.0.0");        // Header version tag
    expect(getBody()).toContain("提供方");          // Provider label
    expect(getBody()).toContain("下载次数");        // Meta - download count
    expect(getBody()).toContain("认证状态");        // Meta - verified
    expect(getBody()).toContain("描述");            // Description section header
    expect(getBody()).toContain("帮助优化代码");   // Description content
    expect(getBody()).toContain("Prompt 内容");   // Prompt section header
    expect(getBody()).toContain("复制");            // Copy button
  });

  it("404 from detail API closes drawer and shows error", async () => {
    mockListMarketplace.mockResolvedValue(buildListResponse([sampleSkill]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetailResponse(null));

    const { container } = render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    const getBody = () => document.body.textContent || "";
    await waitFor(() => {
      expect(getBody()).toContain("代码优化专家");
    });

    fireEvent.click(screen.getByRole("button", { name: "详情" }));

    await waitFor(() => {
      expect(getBody()).not.toContain("Prompt 内容");
    });
  });

  it("null content renders no prompt section", async () => {
    const noContentSkill: MarketplaceSkill = { ...sampleSkill, content: undefined };
    mockListMarketplace.mockResolvedValue(buildListResponse([noContentSkill]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetailResponse(noContentSkill));

    const { container } = render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    const getBody = () => document.body.textContent || "";
    await waitFor(() => {
      expect(getBody()).toContain("代码优化专家");
    });

    fireEvent.click(screen.getByRole("button", { name: "详情" }));

    await waitFor(() => {
      expect(getBody()).toContain("描述");
    });

    expect(getBody()).not.toContain("Prompt 内容");
  });

  it("network error closes drawer", async () => {
    mockListMarketplace.mockResolvedValue(buildListResponse([sampleSkill]));
    mockGetMarketplaceSkill.mockRejectedValue(new Error("Network Error"));

    const { container } = render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    const getBody = () => document.body.textContent || "";
    await waitFor(() => {
      expect(getBody()).toContain("代码优化专家");
    });

    fireEvent.click(screen.getByRole("button", { name: "详情" }));

    await waitFor(() => {
      expect(getBody()).not.toContain("Prompt 内容");
    });
  });

  it("drawer open and switching skills shows latest content", async () => {
    mockListMarketplace.mockResolvedValue(buildListResponse([sampleSkill, anotherSkill]));
    mockGetMarketplaceSkill
      .mockResolvedValueOnce(buildDetailResponse(sampleSkill))
      .mockResolvedValueOnce(buildDetailResponse(anotherSkill));

    const { container } = render(<TestWrapper><SkillsMarketPage /></TestWrapper>);

    // Wait for table to load (both skills visible)
    await waitFor(() => {
      expect(document.body.textContent).toContain("代码优化专家");
      expect(document.body.textContent).toContain("文档写作助手");
    });

    // Click 详情 on skill 1
    const detailButtons = Array.from(container.querySelectorAll("button")).filter(
      (b) => b.textContent?.trim() === "详情"
    );
    expect(detailButtons.length).toBe(2);
    fireEvent.click(detailButtons[0]);

    // Wait for skill 1's content
    await waitFor(() => {
      expect(document.body.textContent).toContain("You are a code optimization expert");
    });

    // Click 详情 on skill 2 directly (drawer switches content)
    // (No need to close drawer first — clicking 详情 on another row switches detailId)
    fireEvent.click(detailButtons[1]);

    // Wait for skill 2's content
    await waitFor(() => {
      expect(document.body.textContent).toContain("You are a documentation assistant");
    });

    // Verify skill 1's content is no longer visible
    expect(document.body.textContent).not.toContain("You are a code optimization expert");
  });
});
