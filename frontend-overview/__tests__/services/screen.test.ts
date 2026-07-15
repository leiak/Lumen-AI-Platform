import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/services/api", () => {
  return {
    default: {
      get: vi.fn(),
    },
  };
});

import api from "@/services/api";
import { screenApi } from "@/services/screen";

const mockGet = (data: unknown) => {
  (api.get as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
    data: { code: 200, data },
  });
};

describe("screenApi", () => {
  beforeEach(() => vi.clearAllMocks());

  it("getOverview unwraps data", async () => {
    mockGet({ total_tenants: 1, total_users: 2, ai_calls: 3 });
    const out = await screenApi.getOverview("24h");
    expect(out.total_tenants).toBe(1);
    expect(api.get).toHaveBeenCalledWith("/screen/overview", { params: { range: "24h" } });
  });

  it("getAiCalls passes granularity", async () => {
    mockGet({ series: [], by_model: [] });
    await screenApi.getAiCalls("7d", "day");
    expect(api.get).toHaveBeenCalledWith("/screen/ai-calls", { params: { range: "7d", granularity: "day" } });
  });

  it("getKnowledge / getWorkflows / getTenantsUsers", async () => {
    mockGet({ total_kbs: 0 });
    await screenApi.getKnowledge("24h");
    expect(api.get).toHaveBeenCalledWith("/screen/knowledge", { params: { range: "24h" } });

    mockGet({ total_runs: 0 });
    await screenApi.getWorkflows("1h");
    expect(api.get).toHaveBeenCalledWith("/screen/workflows", { params: { range: "1h" } });

    mockGet({ tenant_growth: [], user_growth: [], top_active_tenants: [] });
    await screenApi.getTenantsUsers("30d");
    expect(api.get).toHaveBeenCalledWith("/screen/tenants-users", { params: { range: "30d" } });
  });

  it("propagates 401 errors", async () => {
    (api.get as unknown as ReturnType<typeof vi.fn>).mockRejectedValueOnce({
      response: { status: 401 },
    });
    await expect(screenApi.getOverview("24h")).rejects.toBeDefined();
  });

  it("propagates 500 errors", async () => {
    (api.get as unknown as ReturnType<typeof vi.fn>).mockRejectedValueOnce({
      response: { status: 500 },
    });
    await expect(screenApi.getOverview("24h")).rejects.toBeDefined();
  });
});
