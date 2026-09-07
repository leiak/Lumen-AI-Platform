import { describe, expect, it } from "vitest";
import {
  ALL_NODE_REGISTRY,
  ALL_NODE_REGISTRY_LIST,
  allNodeComponents,
} from "@/app/dashboard/workflow/designer/nodeTypes";

describe("designer nodeTypes registry (M30c 22 nodes)", () => {
  it("registers all 20 nodes (8 P1 + 9 P2 + 2 M35 + 1 M36)", () => {
    // M30c 2.0 (2026-09-07): spec originally said 17 / plan said 22 — actual
    // count is 20 (8+9+2+1). 2 start/end placeholders are NOT in this
    // registry (executor handles them).
    expect(ALL_NODE_REGISTRY_LIST.length).toBe(20);
  });

  it("contains every P1 node type", () => {
    const keys = Object.keys(ALL_NODE_REGISTRY);
    for (const t of [
      "input",
      "agent",
      "llm",
      "condition",
      "output",
      "parallel",
      "fan_out",
      "fan_in",
    ]) {
      expect(keys).toContain(t);
    }
  });

  it("contains every P2 node type", () => {
    const keys = Object.keys(ALL_NODE_REGISTRY);
    for (const t of [
      "code",
      "http",
      "tool",
      "knowledge_retrieval",
      "template_transform",
      "parameter_extractor",
      "question_classifier",
      "variable_assigner",
      "variable_aggregator",
    ]) {
      expect(keys).toContain(t);
    }
  });

  it("contains every M35/M36 node type (M30c 2.0 add)", () => {
    // M35 (tts/playbook_inject) + M36 (video_compose) — spec 用 17,实际 22
    const keys = Object.keys(ALL_NODE_REGISTRY);
    for (const t of ["tts", "playbook_inject", "video_compose"]) {
      expect(keys).toContain(t);
    }
  });

  it("allNodeComponents map has a component for every registered node", () => {
    for (const meta of ALL_NODE_REGISTRY_LIST) {
      expect(allNodeComponents[meta.type as string]).toBe(meta.component);
    }
  });

  it("each entry has icon + label + description for the library panel", () => {
    for (const meta of ALL_NODE_REGISTRY_LIST) {
      expect(meta.icon).toBeTruthy();
      expect(meta.label).toBeTruthy();
      expect(meta.description).toBeTruthy();
      expect(meta.color).toBeTruthy();
      expect(meta.category).toBeTruthy();
    }
  });
});
