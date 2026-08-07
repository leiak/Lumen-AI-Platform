// frontend/__tests__/services/wx-publisher-trailing-slash.test.ts
// Regression — 2026-08-07: publish endpoint 报 401, 根因 FastAPI
// redirect_slashes 默认开 + axios 对 307 + POST 自动 strip Authorization
// header 防 token 泄漏, 重定向后无 token → 401.
//
// 修法:wx-publisher service 的集合 POST 路径加尾斜杠, 直接命中
// 后端注册的带尾斜杠路由(/accounts/, /templates/, /drafts/,
// /materials/, /publish/),不走 307 redirect. GET list 不需要修 (GET
// 307 不丢 header, 工作正常).
//
// 反例:`POST /materials/from-kb` 是后端注册的静态子路径(无尾斜杠),
// 前端用 `/wx-publisher/materials/from-kb`(无尾斜杠)直接命中;若
// 加 `/` 反而触发 307 redirect(后端 /from-kb 无尾斜杠)。
//
// 这个测试拦截 services/auth.ts 的 axios 实例,断言 5 个集合 POST
// 路径都以 /wx-publisher/.../ 结尾,任何漏尾斜杠都会 fail;另外单独
// 断言 /from-kb 不带尾斜杠(防回归 — 别不小心把它改成带 /)。
import { describe, expect, it, vi } from "vitest";

const hoisted = vi.hoisted(() => {
  // 用一个共享的 post 函数, 验证所有 create/create-like POST 都走它,
  // 而不是直接构造 request — service 内部就是用 api.post() 调 auth.ts.
  return { postCalls: [] as Array<{ url: string; payload: unknown }> };
});

vi.mock("@/services/auth", () => {
  const api = {
    get: vi.fn(() => Promise.resolve({ data: { code: 200, data: [] } })),
    post: vi.fn((url: string, payload?: unknown) => {
      hoisted.postCalls.push({ url, payload });
      return Promise.resolve({ data: { code: 200, data: { id: 1 } } });
    }),
    put: vi.fn((url: string, payload?: unknown) =>
      Promise.resolve({ data: { code: 200, data: { id: 1 } } })
    ),
    delete: vi.fn(() =>
      Promise.resolve({ data: { code: 200 }, status: 200 })
    ),
  };
  // 单例 default export — service `import api from "./auth"` 拿到这个.
  return { default: api };
});

import {
  accountApi,
  templateApi,
  draftApi,
  draftAiApi,
  materialApi,
  publishApi,
} from "@/services/wx-publisher";

// 5 个集合 create/create-like POST 路径 — 任何漏尾斜杠的都会触发
// FastAPI redirect_slashes → 307 + axios strip Authorization → 401.
// /from-kb 不在列表:后端注册的静态路径是 /from-kb(无 /),带 /
// 才会触发 307 redirect;不参与此断言。
const POSTS_THAT_MUST_HAVE_TRAILING_SLASH: Array<{
  name: string;
  call: () => Promise<unknown>;
}> = [
  {
    name: "accountApi.create",
    call: () => accountApi.create({ name: "x", app_id: "x", app_secret: "x" }),
  },
  {
    name: "templateApi.create",
    call: () =>
      templateApi.create({
        name: "x",
        category: "minimal",
        html_body: "",
        css_variables: {},
      }),
  },
  {
    name: "draftApi.create",
    call: () => draftApi.create({ title: "x" }),
  },
  {
    name: "materialApi.create",
    call: () => materialApi.create({ title: "x", content: "x" }),
  },
  {
    name: "publishApi.createPublish",
    call: () => publishApi.createPublish({ draft_id: 1, account_id: 1 }),
  },
];

describe("wx-publisher service — 集合 POST 路径必须带尾斜杠(防 307 redirect + Authorization strip)", () => {
  for (const { name, call } of POSTS_THAT_MUST_HAVE_TRAILING_SLASH) {
    it(`${name} POST URL 以 / 结尾`, async () => {
      hoisted.postCalls.length = 0;
      await call();
      expect(hoisted.postCalls).toHaveLength(1);
      const url = hoisted.postCalls[0].url;
      expect(
        url.endsWith("/"),
        `${name} POST 路径 ${JSON.stringify(url)} 缺尾斜杠, 会触发 FastAPI redirect_slashes → 307 + axios strip Authorization → 401`
      ).toBe(true);
    });
  }
});

// 反例断言:materialApi.importFromKB 的 URL 必须以 /from-kb 结尾
// (无尾斜杠)。后端注册的路径是 /from-kb(无 /),前端加 / 会触发 307。
describe("wx-publisher service — 静态子路径 importFromKB 必须不带尾斜杠", () => {
  it("materialApi.importFromKB POST URL 以 /from-kb 结尾(无 /)", async () => {
    hoisted.postCalls.length = 0;
    await materialApi.importFromKB({ kb_id: 1, query: "x" });
    expect(hoisted.postCalls).toHaveLength(1);
    const url = hoisted.postCalls[0].url;
    expect(
      url.endsWith("/from-kb") && !url.endsWith("/from-kb/"),
      `importFromKB POST URL ${JSON.stringify(url)} 不应以 /from-kb/ 结尾(后端注册 /from-kb 无 /,带 / 会触发 307)`
    ).toBe(true);
  });
});

// 顺手验:path-param POST/PUT/DELETE 也走带尾斜杠的子路径或单独子路径
// (e.g. /drafts/{id}/sections). 这类不会被 redirect_slashes 拦截, 但
// 风格上保持一致也合理 — 这里只断言「不抛错」, 不强制风格.
describe("wx-publisher service — path-param POST 不抛错", () => {
  it("draftApi.addSection", async () => {
    await expect(
      draftApi.addSection(1, { order_index: 0 })
    ).resolves.toBeDefined();
  });
  it("draftApi.pasteHtml", async () => {
    await expect(draftApi.pasteHtml(1, { html: "" })).resolves.toBeDefined();
  });
  it("draftAiApi.outline", async () => {
    await expect(
      draftAiApi.outline(1, { topic: "x" })
    ).resolves.toBeDefined();
  });
  it("draftAiApi.render", async () => {
    await expect(draftAiApi.render(1, { template_id: 1 })).resolves.toBeDefined();
  });
});