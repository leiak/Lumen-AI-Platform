// frontend/__tests__/skills/market-detail-types.test.tsx
// Render-level tests for /dashboard/skills/market with mixed skill types.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { ConfigProvider, App as AntApp } from "antd";

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
    <AntApp>{children}</AntApp>
  </ConfigProvider>
);

const promptSkill: MarketplaceSkill = {
  id: 1, name: "测试工程师", category: "testing",
  description: "自动生成测试用例", downloads: 543, rating: 4.5,
  type: "prompt",
  content: "You are a testing engineer.",
};

const scriptSkill: MarketplaceSkill = {
  id: 2, name: "JSON格式化", category: "code",
  description: "格式化 JSON 字符串", downloads: 100, rating: 4.2,
  type: "script",
  type_config: {
    code: "import json\ndef main(s):\n    return json.dumps(json.loads(s), indent=2)",
    runtime: "python-3.11",
    timeout: 10,
  },
};

const httpSkill: MarketplaceSkill = {
  id: 3, name: "天气查询", category: "data",
  description: "查询指定城市天气", downloads: 200, rating: 4.0,
  type: "http",
  type_config: {
    url: "https://api.weather.com/v1/forecast",
    method: "GET",
    timeout: 15,
    auth: { type: "bearer", credential_ref: "${WEATHER_API_KEY}" },
  },
};

const buildListResponse = (list: MarketplaceSkill[]) => ({
  data: { code: 200, message: "ok", data: list, total: list.length, page: 1, page_size: 20 },
});
const buildDetailResponse = (skill: MarketplaceSkill) => ({
  data: { code: 200, message: "ok", data: skill },
});

describe("SkillsMarketPage - skill type dispatch", () => {
  beforeEach(() => {
    mockListMarketplace.mockReset();
    mockInstallSkill.mockReset();
    mockGetMarketplaceSkill.mockReset();
  });

  it("prompt type drawer shows Prompt 内容 section", async () => {
    mockListMarketplace.mockResolvedValue(buildListResponse([promptSkill]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetailResponse(promptSkill));

    render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    await waitFor(() => expect(document.body.textContent).toContain("测试工程师"));

    const detailBtns = Array.from(document.querySelectorAll("button")).filter(
      (b) => b.textContent?.trim() === "详情"
    );
    fireEvent.click(detailBtns[0]);
    await waitFor(() => expect(document.body.textContent).toContain("You are a testing engineer"));

    expect(document.body.textContent).toContain("Prompt 内容");
    expect(document.body.textContent).toContain("复制");
  });

  it("script type drawer shows code block, hides prompt section", async () => {
    mockListMarketplace.mockResolvedValue(buildListResponse([scriptSkill]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetailResponse(scriptSkill));

    render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    await waitFor(() => expect(document.body.textContent).toContain("JSON格式化"));

    const detailBtns = Array.from(document.querySelectorAll("button")).filter(
      (b) => b.textContent?.trim() === "详情"
    );
    fireEvent.click(detailBtns[0]);

    await waitFor(() => expect(document.body.textContent).toContain("import json"));
    expect(document.body.textContent).toContain("python-3.11");
    expect(document.body.textContent).toContain("代码");
    expect(document.body.textContent).not.toContain("Prompt 内容");
  });

  it("http type drawer shows URL and method, hides prompt section", async () => {
    mockListMarketplace.mockResolvedValue(buildListResponse([httpSkill]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetailResponse(httpSkill));

    render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    await waitFor(() => expect(document.body.textContent).toContain("天气查询"));

    const detailBtns = Array.from(document.querySelectorAll("button")).filter(
      (b) => b.textContent?.trim() === "详情"
    );
    fireEvent.click(detailBtns[0]);

    await waitFor(() => expect(document.body.textContent).toContain("https://api.weather.com/v1/forecast"));
    expect(document.body.textContent).toContain("GET");
    expect(document.body.textContent).toContain("API");
    // Auth credential VALUE should NOT be shown (only the ref name)
    expect(document.body.textContent).not.toContain("Bearer ");
    expect(document.body.textContent).not.toContain("Prompt 内容");
  });

  it("type tag rendered in drawer title", async () => {
    mockListMarketplace.mockResolvedValue(buildListResponse([scriptSkill]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetailResponse(scriptSkill));

    render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    await waitFor(() => expect(document.body.textContent).toContain("JSON格式化"));

    const detailBtns = Array.from(document.querySelectorAll("button")).filter(
      (b) => b.textContent?.trim() === "详情"
    );
    fireEvent.click(detailBtns[0]);
    await waitFor(() => expect(document.body.textContent).toContain("import json"));

    const tags = document.querySelectorAll(".ant-tag");
    const tagTexts = Array.from(tags).map((t) => t.textContent || "");
    expect(tagTexts.some((t) => t === "脚本")).toBe(true);
  });

  it("marketplace list type column shows correct tag", async () => {
    mockListMarketplace.mockResolvedValue(buildListResponse([promptSkill, scriptSkill, httpSkill]));

    render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    await waitFor(() => {
      expect(document.body.textContent).toContain("测试工程师");
      expect(document.body.textContent).toContain("JSON格式化");
      expect(document.body.textContent).toContain("天气查询");
    });

    const tags = document.querySelectorAll(".ant-tag");
    const tagTexts = Array.from(tags).map((t) => t.textContent || "");
    expect(tagTexts).toContain("提示词");
    expect(tagTexts).toContain("脚本");
    expect(tagTexts).toContain("API");
  });

  it("unknown type falls back to prompt rendering", async () => {
    const unknownSkill: MarketplaceSkill = {
      ...promptSkill, id: 99, type: "future_type_xyz",
    };
    mockListMarketplace.mockResolvedValue(buildListResponse([unknownSkill]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetailResponse(unknownSkill));

    render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    await waitFor(() => expect(document.body.textContent).toContain("测试工程师"));

    const detailBtns = Array.from(document.querySelectorAll("button")).filter(
      (b) => b.textContent?.trim() === "详情"
    );
    fireEvent.click(detailBtns[0]);
    await waitFor(() => expect(document.body.textContent).toContain("You are a testing engineer"));

    expect(document.body.textContent).toContain("Prompt 内容");
  });

  it("missing type field falls back to prompt rendering", async () => {
    const legacySkill: MarketplaceSkill = {
      ...promptSkill, id: 100, type: undefined,
    };
    mockListMarketplace.mockResolvedValue(buildListResponse([legacySkill]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetailResponse(legacySkill));

    render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    await waitFor(() => expect(document.body.textContent).toContain("测试工程师"));

    const detailBtns = Array.from(document.querySelectorAll("button")).filter(
      (b) => b.textContent?.trim() === "详情"
    );
    fireEvent.click(detailBtns[0]);
    await waitFor(() => expect(document.body.textContent).toContain("You are a testing engineer"));

    expect(document.body.textContent).toContain("Prompt 内容");
  });

  it("script with input_schema shows interface definition", async () => {
    const scriptWithSchema: MarketplaceSkill = {
      ...scriptSkill, id: 50,
      type_config: {
        ...scriptSkill.type_config,
        input_schema: { type: "object", properties: { s: { type: "string" } }, required: ["s"] },
        output_schema: { type: "string" },
      },
    };
    mockListMarketplace.mockResolvedValue(buildListResponse([scriptWithSchema]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetailResponse(scriptWithSchema));

    render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    await waitFor(() => expect(document.body.textContent).toContain("JSON格式化"));

    const detailBtns = Array.from(document.querySelectorAll("button")).filter(
      (b) => b.textContent?.trim() === "详情"
    );
    fireEvent.click(detailBtns[0]);

    await waitFor(() => expect(document.body.textContent).toContain("import json"));
    expect(document.body.textContent).toContain("接口定义");
    expect(document.body.textContent).toContain("输入:");
    expect(document.body.textContent).toContain("输出:");
  });

  it("http with headers and body template shows them", async () => {
    const httpFull: MarketplaceSkill = {
      ...httpSkill, id: 60,
      type_config: {
        ...httpSkill.type_config,
        method: "POST",
        headers: { "X-API-Version": "3", "Content-Type": "application/json" },
        body_template: '{"city": "{{city}}"}',
      },
    };
    mockListMarketplace.mockResolvedValue(buildListResponse([httpFull]));
    mockGetMarketplaceSkill.mockResolvedValue(buildDetailResponse(httpFull));

    render(<TestWrapper><SkillsMarketPage /></TestWrapper>);
    await waitFor(() => expect(document.body.textContent).toContain("天气查询"));

    const detailBtns = Array.from(document.querySelectorAll("button")).filter(
      (b) => b.textContent?.trim() === "详情"
    );
    fireEvent.click(detailBtns[0]);

    await waitFor(() => expect(document.body.textContent).toContain("https://api.weather.com"));
    expect(document.body.textContent).toContain("Headers");
    expect(document.body.textContent).toContain("X-API-Version");
    expect(document.body.textContent).toContain("Body 模板");
    expect(document.body.textContent).toContain("{{city}}");
  });
});
