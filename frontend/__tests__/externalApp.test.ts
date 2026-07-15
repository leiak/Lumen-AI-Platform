import { describe, it, expect, vi } from "vitest";

vi.mock("@/services/auth", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

import api from "@/services/auth";
import { externalAppApi } from "@/services/externalApp";

describe("externalAppApi", () => {
  it("list unwraps data + total/page/page_size from flat envelope", async () => {
    (api.get as any).mockResolvedValueOnce({
      data: {
        code: 200,
        message: "ok",
        data: [{ id: 1, name: "shop" } as any],
        total: 5,
        page: 2,
        page_size: 20,
      },
    });
    const out = await externalAppApi.list({ page: 2 });
    expect(out.items).toHaveLength(1);
    expect(out.total).toBe(5);
    expect(out.page).toBe(2);
    expect(out.page_size).toBe(20);
  });

  it("create unwraps data.data", async () => {
    (api.post as any).mockResolvedValueOnce({
      data: { code: 200, message: "ok", data: { id: 7, app_secret_plain: "s" } },
    });
    const out = await externalAppApi.create({ name: "x", allowed_origins: [] } as any);
    expect(out.id).toBe(7);
    expect(out.app_secret_plain).toBe("s");
  });

  it("update unwraps data.data", async () => {
    (api.patch as any).mockResolvedValueOnce({
      data: { code: 200, message: "ok", data: { id: 1, name: "y" } },
    });
    const out = await externalAppApi.update(1, { name: "y" });
    expect(out.name).toBe("y");
  });

  it("regenerateSecret unwraps data.data with plain secret", async () => {
    (api.post as any).mockResolvedValueOnce({
      data: { code: 200, message: "ok", data: { id: 1, app_secret_plain: "new" } },
    });
    const out = await externalAppApi.regenerateSecret(1);
    expect(out.app_secret_plain).toBe("new");
  });

  it("remove returns code+message", async () => {
    (api.delete as any).mockResolvedValueOnce({
      data: { code: 200, message: "Deleted" },
    });
    const out = await externalAppApi.remove(1);
    expect(out.code).toBe(200);
    expect(out.message).toBe("Deleted");
  });
});
