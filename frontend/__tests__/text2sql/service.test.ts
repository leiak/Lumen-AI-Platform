// frontend/__tests__/text2sql/service.test.ts
// M33: minimal smoke test for the text2sql frontend service layer.

import { describe, expect, it, vi } from "vitest";

// Mock the axios instance from auth so we don't need a real network
vi.mock("@/services/auth", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

import api from "@/services/auth";
import { text2SqlApi } from "@/services/text2sql";

describe("text2SqlApi", () => {
  it("ask posts to /text2sql/ask and unwraps data", async () => {
    (api.post as any).mockResolvedValueOnce({
      data: { code: 200, data: { query_id: 1, status: "success" } },
    });
    const res = await text2SqlApi.ask({
      data_source_id: 1,
      question: "x",
    });
    expect(api.post).toHaveBeenCalledWith("/text2sql/ask", {
      data_source_id: 1,
      question: "x",
    });
    expect(res.status).toBe("success");
  });

  it("listHistory unpaginated response", async () => {
    (api.get as any).mockResolvedValueOnce({
      data: {
        code: 200,
        data: [{ id: 1, question_preview: "x" }],
        total: 1,
        page: 1,
        page_size: 20,
      },
    });
    const res = await text2SqlApi.listHistory();
    expect(res.items).toHaveLength(1);
    expect(res.total).toBe(1);
  });

  it("getSchema passes data_source_id as query param", async () => {
    (api.get as any).mockResolvedValueOnce({
      data: { code: 200, data: { data_source_id: 1, table_count: 5 } },
    });
    const res = await text2SqlApi.getSchema(1);
    expect(api.get).toHaveBeenCalledWith(
      "/text2sql/schema",
      expect.objectContaining({ params: { data_source_id: 1 } }),
    );
    expect(res.table_count).toBe(5);
  });
});
