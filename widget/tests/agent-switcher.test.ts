import { describe, it, expect } from "vitest";
import { fixture, html, elementUpdated } from "@open-wc/testing";
import "../src/components/AgentSwitcher";
import type { AgentSwitcher, AgentChangeDetail } from "../src/components/AgentSwitcher";

describe("<lc-agent-switcher>", () => {
  it("renders one option per agent", async () => {
    const el = await fixture<AgentSwitcher>(html`
      <lc-agent-switcher
        .options=${[
          { id: 1, name: "A", type: "agent" },
          { id: 2, name: "B", type: "agent" },
        ]}
      ></lc-agent-switcher>
    `);
    await elementUpdated(el);
    const opts = el.shadowRoot?.querySelectorAll("option");
    expect(opts).toHaveLength(2);
  });

  it("emits agent-change on select", async () => {
    const el = await fixture<AgentSwitcher>(html`
      <lc-agent-switcher
        .options=${[{ id: 1, name: "A", type: "agent" }]}
      ></lc-agent-switcher>
    `);
    await elementUpdated(el);
    let received: AgentChangeDetail | null = null;
    el.addEventListener("agent-change", (e) => {
      received = (e as CustomEvent<AgentChangeDetail>).detail;
    });
    const select = el.shadowRoot?.querySelector("select") as HTMLSelectElement | null;
    expect(select).not.toBeNull();
    select!.value = "1";
    select!.dispatchEvent(new Event("change"));
    expect(received).toEqual({
      id: 1,
      options: { id: 1, name: "A", type: "agent" },
    });
  });
});
