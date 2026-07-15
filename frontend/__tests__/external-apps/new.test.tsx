import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { App as AntdApp } from "antd";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/services/externalApp", () => ({
  externalAppApi: {
    create: vi.fn().mockResolvedValue({
      id: 1, name: "shop", app_key: "lc_pub_x", app_secret_plain: "sec",
      allowed_origins: [], allowed_agent_ids: [], allowed_team_ids: [],
      rate_limit_per_min: 60, scopes: "chat:stream", is_active: true,
      tenant_id: 1, description: null, created_by: null, last_used_at: null,
      created_at: "", updated_at: "", allowed_agent_names: [], allowed_team_names: [],
    }),
  },
  listAgentOptions: vi.fn().mockResolvedValue([]),
  listTeamOptions: vi.fn().mockResolvedValue([]),
}));

import NewExternalAppPage from "@/app/dashboard/external-apps/new/page";

describe("NewExternalAppPage", () => {
  it("renders the new form", () => {
    render(<AntdApp><NewExternalAppPage /></AntdApp>);
    expect(screen.getByText("新建外部应用")).toBeInTheDocument();
    expect(screen.getByLabelText("名称")).toBeInTheDocument();
  });
});
