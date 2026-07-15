// frontend/__tests__/external-apps/detail-agent-whitelist.test.tsx
// Page-level test for the new agent/team whitelist Selects + Alert on
// /dashboard/external-apps/[id]. Mirrors the wrapper pattern from the
// sibling detail.test.tsx (uses <AntdApp> since the page already pulls
// message via App.useApp()).
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { App as AntdApp } from "antd";

const mockGet = vi.fn();
const mockUpdate = vi.fn();
const mockRegenerate = vi.fn();
const mockUsage = vi.fn();
const mockListAgentOptions = vi.fn();
const mockListTeamOptions = vi.fn();

vi.mock("@/services/externalApp", () => ({
  externalAppApi: {
    get: (...args: any[]) => mockGet(...args),
    update: (...args: any[]) => mockUpdate(...args),
    regenerateSecret: (...args: any[]) => mockRegenerate(...args),
    usage: (...args: any[]) => mockUsage(...args),
  },
  listAgentOptions: (...args: any[]) => mockListAgentOptions(...args),
  listTeamOptions: (...args: any[]) => mockListTeamOptions(...args),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "155" }),
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/components/external-apps/SecretRevealModal", () => ({
  default: () => null,
}));
vi.mock("@/components/external-apps/UsageTab", () => ({
  default: () => null,
}));

import ExternalAppDetailPage from "@/app/dashboard/external-apps/[id]/page";
import type { ExternalApp } from "@/types/api";

function makeApp(over: Partial<ExternalApp> = {}): ExternalApp {
  return {
    id: 155,
    tenant_id: 1,
    name: "官网客服",
    app_key: "lc_pub_xxx",
    allowed_origins: ["https://shop.example.com"],
    allowed_agent_ids: [10, 11],
    allowed_team_ids: [],
    scopes: "chat:stream",
    rate_limit_per_min: 60,
    is_active: true,
    description: null,
    created_by: 1,
    last_used_at: null,
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-01T00:00:00Z",
    allowed_agent_names: ["Agent A", "Agent B"],
    allowed_team_names: [],
    ...over,
  };
}

describe("ExternalAppDetailPage — agent/team whitelist", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUpdate.mockResolvedValue(makeApp());
    mockRegenerate.mockResolvedValue({ ...makeApp(), app_secret_plain: "new" });
    mockUsage.mockResolvedValue({
      last_used_at: null,
      active_visitors_7d: 0,
      total_conversations: 0,
      token_issues_7d: 0,
      last_7d_daily: [0, 0, 0, 0, 0, 0, 0],
    });
  });

  it("loads agent and team options on mount and renders 2 multi-Selects in the scope tab", async () => {
    mockGet.mockResolvedValue(makeApp());
    mockListAgentOptions.mockResolvedValue([
      { id: 10, name: "Agent A" },
      { id: 11, name: "Agent B" },
    ]);
    mockListTeamOptions.mockResolvedValue([{ id: 7, name: "Team T" }]);

    render(
      <AntdApp>
        <ExternalAppDetailPage />
      </AntdApp>
    );

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith(155);
      expect(mockListAgentOptions).toHaveBeenCalledTimes(1);
      expect(mockListTeamOptions).toHaveBeenCalledTimes(1);
    });

    // Switch to the 授权范围 tab — AntD Tabs render role=tab, click() works in jsdom
    const scopeTab = await screen.findByRole("tab", { name: /授权范围/ });
    fireEvent.click(scopeTab);

    // The two new Form.Items carry the labels "允许的 Agents" and "允许的 Teams".
    // Asserting on the label is more robust than the AntD multi-Select
    // placeholder, which is rendered as a CSS pseudo-element / data attr
    // rather than the input's `placeholder` attribute.
    expect(
      await screen.findByText("允许的 Agents")
    ).toBeInTheDocument();
    expect(
      await screen.findByText("允许的 Teams")
    ).toBeInTheDocument();
  });

  it("shows a warning Alert when both whitelists are empty", async () => {
    mockGet.mockResolvedValue(
      makeApp({ allowed_agent_ids: [], allowed_team_ids: [] })
    );
    mockListAgentOptions.mockResolvedValue([]);
    mockListTeamOptions.mockResolvedValue([]);

    render(
      <AntdApp>
        <ExternalAppDetailPage />
      </AntdApp>
    );

    const scopeTab = await screen.findByRole("tab", { name: /授权范围/ });
    fireEvent.click(scopeTab);

    expect(
      await screen.findByText(/该 app 当前没有可用的 Agent 或 Team/i)
    ).toBeInTheDocument();
  });
});
