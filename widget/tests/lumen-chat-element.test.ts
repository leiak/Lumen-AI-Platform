import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { fixture, html, elementUpdated } from "@open-wc/testing";

import "../src/LumenChat";

describe("<lumen-chat>", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    // Wipe any localStorage left over from a previous test — the widget's
    // AuthStore persists the JWT in localStorage and skips refetch when
    // the cached token is still fresh, which would make allowedAgents
    // empty for any test that runs after the first token-issuing one.
    try { localStorage.clear(); } catch {}
    // Stub the token endpoint so _init() resolves with `ready = true`
    // and we render the full UI (header + messages + input).
    globalThis.fetch = vi.fn(async (url: any) => {
      const s = String(url);
      if (s.includes("/api/v1/external/auth/token")) {
        return new Response(
          JSON.stringify({
            code: 200,
            data: {
              token: "fake.jwt.token",
              expires_in: 1800,
              allowed_agents: [{ id: 1, name: "Default Agent" }],
              allowed_teams: [],
              visitor_id: 1,
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
    }) as any;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("registers as a custom element", async () => {
    const el = await fixture<HTMLElement>(html`<lumen-chat server="http://x" app-key="lc_pub_test"></lumen-chat>`);
    expect(el.tagName.toLowerCase()).toBe("lumen-chat");
  });

  it("reflects attributes to properties", async () => {
    const el = (await fixture<HTMLElement>(
      html`<lumen-chat server="http://x" app-key="lc_pub_test" agent-id="42" theme="dark"></lumen-chat>`
    )) as any;
    expect(el.server).toBe("http://x");
    expect(el.appKey).toBe("lc_pub_test");
    expect(el.agentId).toBe(42);
    expect(el.theme).toBe("dark");
  });

  it("renders the header with default title", async () => {
    const el = await fixture<HTMLElement>(html`<lumen-chat server="http://x" app-key="lc_pub_test"></lumen-chat>`);
    await elementUpdated(el);
    // wait for _init() to flip ready = true
    await new Promise((r) => setTimeout(r, 50));
    await elementUpdated(el);
    const header = el.shadowRoot?.querySelector(".lc-header h1");
    expect(header?.textContent?.trim()).toBe("AI 助手");
  });

  // === M21: KB badge in header ===
  // The token endpoint stub above returns an agent with no
  // knowledge_bases → the badge should still render but be marked
  // disabled via data-kb-count="0" + the "未配置知识库" tooltip.
  it("renders the KB badge in the header", async () => {
    const el = await fixture<HTMLElement>(html`<lumen-chat server="http://x" app-key="lc_pub_test"></lumen-chat>`);
    await elementUpdated(el);
    await new Promise((r) => setTimeout(r, 50));
    await elementUpdated(el);
    const badge = el.shadowRoot?.querySelector("[data-testid=\"lc-kb-badge\"]") as HTMLElement | null;
    expect(badge).toBeTruthy();
    expect(badge?.getAttribute("data-kb-count")).toBe("0");
    expect(badge?.getAttribute("title")).toBe("未配置知识库");
  });

  it("shows the bound KB names in the badge tooltip", async () => {
    // Override the fetch stub for this test to include knowledge_bases.
    globalThis.fetch = vi.fn(async (url: any) => {
      if (String(url).includes("/api/v1/external/auth/token")) {
        return new Response(
          JSON.stringify({
            code: 200,
            data: {
              token: "fake.jwt.token",
              expires_in: 1800,
              allowed_agents: [
                {
                  id: 1,
                  name: "Sales Agent",
                  knowledge_bases: [
                    { id: 10, name: "Product Manual", status: "active" },
                    { id: 11, name: "Pricing Policy", status: "active" },
                  ],
                },
              ],
              allowed_teams: [],
              visitor_id: 1,
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
    }) as any;

    const el = await fixture<HTMLElement>(html`<lumen-chat server="http://x" app-key="lc_pub_test"></lumen-chat>`);
    await elementUpdated(el);
    await new Promise((r) => setTimeout(r, 50));
    await elementUpdated(el);
    const badge = el.shadowRoot?.querySelector("[data-testid=\"lc-kb-badge\"]") as HTMLElement | null;
    expect(badge).toBeTruthy();
    expect(badge?.getAttribute("data-kb-count")).toBe("2");
    expect(badge?.getAttribute("title")).toBe("使用知识库: Product Manual, Pricing Policy");
  });

  it("hides the KB badge when the active target is a team", async () => {
    globalThis.fetch = vi.fn(async (url: any) => {
      if (String(url).includes("/api/v1/external/auth/token")) {
        return new Response(
          JSON.stringify({
            code: 200,
            data: {
              token: "fake.jwt.token",
              expires_in: 1800,
              allowed_agents: [],
              allowed_teams: [{ id: 99, name: "Support Team" }],
              visitor_id: 1,
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
    }) as any;

    const el = await fixture<HTMLElement>(html`<lumen-chat server="http://x" app-key="lc_pub_test"></lumen-chat>`);
    await elementUpdated(el);
    await new Promise((r) => setTimeout(r, 50));
    await elementUpdated(el);
    const badge = el.shadowRoot?.querySelector("[data-testid=\"lc-kb-badge\"]");
    expect(badge).toBeNull();
  });
});
