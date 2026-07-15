import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { fixture, html } from "@open-wc/testing";

import "../src/LumenChat";
import type { LumenChat } from "../src/LumenChat";

describe("<lumen-chat> theme", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    // Stub the token endpoint so _init() resolves with `ready = true`.
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

  it("reflects theme=light attribute", async () => {
    const el = (await fixture<HTMLElement>(
      html`<lumen-chat server="http://x" app-key="lc_pub_test" theme="light"></lumen-chat>`
    )) as LumenChat;
    expect(el.getAttribute("theme")).toBe("light");
    expect(el.theme).toBe("light");
  });

  it("accepts dark and auto", async () => {
    const elDark = (await fixture<HTMLElement>(
      html`<lumen-chat server="http://x" app-key="lc_pub_test" theme="dark"></lumen-chat>`
    )) as LumenChat;
    expect(elDark.theme).toBe("dark");

    const elAuto = (await fixture<HTMLElement>(
      html`<lumen-chat server="http://x" app-key="lc_pub_test" theme="auto"></lumen-chat>`
    )) as LumenChat;
    expect(elAuto.theme).toBe("auto");
  });
});
