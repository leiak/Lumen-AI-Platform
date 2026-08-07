// frontend/__tests__/services/wx-publisher-error-extract.test.ts
// Regression — 2026-08-07: 修 dev 体验。
//
// unwrapSingle / unwrapPaginated 现在会从 axios response.data 里提取
// 4xx/5xx 错误消息。FastAPI HTTPException 的 body 是 {detail: string|object},
// 项目标准信封是 {code, message, data},还有兜底 "request failed" / "list failed"。
//
// 这里锁住四种来源,确保前端 toast 显示真实错误,而不是
// "Request failed with status code 409" 这种无用信息。
import { describe, expect, it, vi, beforeEach } from "vitest";

const hoisted = vi.hoisted(() => ({
  postMock: vi.fn(),
  getMock: vi.fn(),
}));

vi.mock("@/services/auth", () => {
  const api = {
    get: hoisted.getMock,
    post: hoisted.postMock,
    put: vi.fn(),
    delete: vi.fn(),
  };
  return { default: api };
});

import { publishApi, draftApi } from "@/services/wx-publisher";

describe("wx-publisher service — unwrapSingle 错误消息提取", () => {
  beforeEach(() => {
    hoisted.postMock.mockReset();
    hoisted.getMock.mockReset();
  });

  it("409 with detail as string → toast 显示 string detail", async () => {
    hoisted.postMock.mockResolvedValueOnce({
      data: { detail: "draft not found" },
      status: 404,
    });
    await expect(
      publishApi.createPublish({ draft_id: 1, account_id: 1 })
    ).rejects.toThrow("draft not found");
  });

  it("409 with structured detail {message, status, published_at} → 提 message", async () => {
    // 重复发布已发布草稿时后端返的形状(publish_service.py:147-160)
    hoisted.postMock.mockResolvedValueOnce({
      data: {
        detail: {
          message: "draft is in 'published' state, cannot republish",
          status: "published",
          published_at: "2026-08-07T02:03:19",
        },
      },
      status: 409,
    });
    await expect(
      publishApi.createPublish({ draft_id: 1, account_id: 1 })
    ).rejects.toThrow("draft is in 'published' state, cannot republish");
  });

  it("项目标准信封 {code: !200, message} → 提 message 字段", async () => {
    hoisted.postMock.mockResolvedValueOnce({
      data: { code: 422, message: "字段 X 校验失败" },
      status: 422,
    });
    await expect(
      publishApi.createPublish({ draft_id: 1, account_id: 1 })
    ).rejects.toThrow("字段 X 校验失败");
  });

  it("空 detail + 无 message → 兜底 'request failed'", async () => {
    hoisted.postMock.mockResolvedValueOnce({
      data: {},
      status: 500,
    });
    await expect(
      publishApi.createPublish({ draft_id: 1, account_id: 1 })
    ).rejects.toThrow("request failed");
  });

  it("unwrapPaginated 同样支持 4xx detail 提取", async () => {
    hoisted.getMock.mockResolvedValueOnce({
      data: { detail: "draft list access denied" },
      status: 403,
    });
    await expect(draftApi.list({})).rejects.toThrow("draft list access denied");
  });
});