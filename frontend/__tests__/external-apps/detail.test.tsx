import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { App as AntdApp } from "antd";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "1" }),
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/services/externalApp", () => ({
  externalAppApi: {
    get: vi.fn().mockResolvedValue({
      id: 1,
      name: "shop",
      app_key: "lc_pub_x",
      is_active: true,
      allowed_origins: ["https://shop.example.com"],
      allowed_agent_ids: [],
      allowed_team_ids: [],
      rate_limit_per_min: 60,
      scopes: "chat:stream",
      tenant_id: 1,
      description: null,
      created_by: null,
      last_used_at: null,
      created_at: "",
      updated_at: "",
      allowed_agent_names: [],
      allowed_team_names: [],
    }),
    update: vi.fn(),
    regenerateSecret: vi.fn(),
    usage: vi.fn().mockResolvedValue({
      last_used_at: null,
      active_visitors_7d: 0,
      total_conversations: 0,
      token_issues_7d: 0,
      last_7d_daily: [0, 0, 0, 0, 0, 0, 0],
    }),
  },
  listAgentOptions: vi.fn().mockResolvedValue([]),
  listTeamOptions: vi.fn().mockResolvedValue([]),
}));

import ExternalAppDetailPage from "@/app/dashboard/external-apps/[id]/page";

describe("ExternalAppDetailPage", () => {
  it("renders the three tabs", async () => {
    render(
      <AntdApp>
        <ExternalAppDetailPage />
      </AntdApp>
    );
    await waitFor(() => expect(screen.getByText("基础信息")).toBeInTheDocument());
    expect(screen.getByText("授权范围")).toBeInTheDocument();
    expect(screen.getByText("用量统计")).toBeInTheDocument();
  });
});
