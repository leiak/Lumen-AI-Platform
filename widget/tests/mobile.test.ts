import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { fixture, html, elementUpdated } from "@open-wc/testing";

import "../src/LumenChat";

describe("<lumen-chat> mobile", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
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

  it("renders inside Shadow DOM", async () => {
    const el = await fixture<HTMLElement>(html`<lumen-chat server="http://x" app-key="lc_pub_test"></lumen-chat>`);
    await elementUpdated(el);
    // wait for _init() to flip ready = true
    await new Promise((r) => setTimeout(r, 50));
    await elementUpdated(el);
    const container = el.shadowRoot?.querySelector(".lc-container");
    expect(container).toBeTruthy();
  });
});
