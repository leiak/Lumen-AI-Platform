import { describe, expect, it } from "vitest";
import {
  P2_NODE_REGISTRY,
  P2_NODE_REGISTRY_LIST,
  p2NodeComponents,
} from "@/app/dashboard/workflow/designer/nodeTypes";

describe("designer nodeTypes registry (M30c)", () => {
  it("registers all 9 P2 nodes", () => {
    // M30c head pain: 9 P2 nodes were shipped with Node.tsx files but
    // never wired into the canvas. After M30c they must all be in
    // the registry AND in the canvas map.
    expect(P2_NODE_REGISTRY_LIST.length).toBe(9);
    const keys = Object.keys(P2_NODE_REGISTRY);
    expect(keys).toContain("code");
    expect(keys).toContain("http");
    expect(keys).toContain("tool");
    expect(keys).toContain("knowledge_retrieval");
    expect(keys).toContain("template_transform");
    expect(keys).toContain("parameter_extractor");
    expect(keys).toContain("question_classifier");
    expect(keys).toContain("variable_assigner");
    expect(keys).toContain("variable_aggregator");
  });

  it("p2NodeComponents map has the same keys as the registry", () => {
    for (const meta of P2_NODE_REGISTRY_LIST) {
      expect(p2NodeComponents[meta.type as string]).toBe(meta.component);
    }
  });

  it("each entry has icon + label + description for the library panel", () => {
    for (const meta of P2_NODE_REGISTRY_LIST) {
      expect(meta.icon).toBeTruthy();
      expect(meta.label).toBeTruthy();
      expect(meta.description).toBeTruthy();
    }
  });
});
