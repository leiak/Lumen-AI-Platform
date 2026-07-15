// frontend/__tests__/skills/market-detail-m17.test.tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, waitFor, fireEvent } from "@testing-library/react";
import { ConfigProvider, App as AntApp } from "antd";

const mockListMarketplace = vi.fn();
const mockGetMarketplaceSkill = vi.fn();
vi.mock("@/services/skills", () => ({
  skillsApi: {
    listMarketplace: (...args: any[]) => mockListMarketplace(...args),
    getMarketplaceSkill: (...args: any[]) => mockGetMarketplaceSkill(...args),
    installSkill: vi.fn(),
    listInstalled: vi.fn(),
    uninstallSkill: vi.fn(),
    getCategories: vi.fn(),
  },
}));

import SkillsMarketPage from "@/app/dashboard/skills/market/page";
import type { MarketplaceSkill } from "@/services/skills";

const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider><AntApp>{children}</AntApp></ConfigProvider>
);

const kbSkill: MarketplaceSkill = {
  id: 10, name: "代码问答", category: "code",
  description: "查询代码知识库", downloads: 200, rating: 4.5,
  type: "knowledge_retrieval",
  type_config: { kb_id: 1, top_k: 3, score_threshold: 0.7, query_template: "What is {{topic}}?" },
};

const toolSkill: MarketplaceSkill = {
  id: 11, name: "工作流列表", category: "data",
  description: "列出工作流", downloads: 100, rating: 4.2,
  type: "tool",
  type_config: { mcp_server: "demo-mcp", tool_name: "list_workflows" },
};

const buildList = (list: MarketplaceSkill[]) => ({
  data: { code: 200, message: "ok", data: list, total: list.length, page: 1, page_size: 20 },
});
const buildDetail = (skill: MarketplaceSkill) => ({
  data: { code: 200, message: "ok", data: skill },
});

describe("SkillsMarketPage - kb/tool detail (M17)", () => {
  beforeEach(() => {
    mockListMarketplace.mockReset();
    mockGetMarketplaceSkill.mockReset();
  });

  it("kb type drawer shows KB config", async () => {
    mockListMarketplace.mockResolvedValue(buildList([kbSkill]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetail(kbSkill));

    render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    await waitFor(() => expect(document.body.textContent).toContain("代码问答"));

    const detailBtn = Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent?.trim() === "详情"
    );
    fireEvent.click(detailBtn!);
    await waitFor(() => expect(document.body.textContent).toContain("查询代码知识库"));

    expect(document.body.textContent).toContain("知识库");
    expect(document.body.textContent).toContain("KB ID");
    expect(document.body.textContent).toContain("Top K");
    expect(document.body.textContent).toContain("查询模板");
    expect(document.body.textContent).toContain("{{topic}}");
  });

  it("tool type drawer shows MCP config", async () => {
    mockListMarketplace.mockResolvedValue(buildList([toolSkill]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetail(toolSkill));

    render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    await waitFor(() => expect(document.body.textContent).toContain("工作流列表"));

    const detailBtn = Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent?.trim() === "详情"
    );
    fireEvent.click(detailBtn!);
    await waitFor(() => expect(document.body.textContent).toContain("列出工作流"));

    expect(document.body.textContent).toContain("工具");
    expect(document.body.textContent).toContain("MCP Server");
    expect(document.body.textContent).toContain("demo-mcp");
    expect(document.body.textContent).toContain("list_workflows");
  });
});
