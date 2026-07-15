// frontend/__tests__/workflow/_base/hooks/useAvailableVarList.test.ts
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { WorkflowNode, WorkflowEdge } from "@/services/workflow";
import { useAvailableVarList, getBeforeNodes } from "@/components/workflow/_base/hooks/useAvailableVarList";

const n = (id: string, type: string, config: any = {}): WorkflowNode => ({
  id, type, config, position: { x: 0, y: 0 },
});
const e = (id: string, source: string, target: string): WorkflowEdge => ({
  id, source, target,
});

describe("getBeforeNodes", () => {
  it("returns all transitive upstream nodes", () => {
    const nodes = [n("a", "input"), n("b", "llm"), n("c", "output")];
    const edges = [e("e1", "a", "b"), e("e2", "b", "c")];
    const result = getBeforeNodes("c", nodes, edges);
    expect(result.map((x) => x.id).sort()).toEqual(["a", "b"]);
  });

  it("returns [] when no upstream", () => {
    const nodes = [n("a", "input")];
    const result = getBeforeNodes("a", nodes, []);
    expect(result).toEqual([]);
  });

  it("includes all branches (no pruning in P1)", () => {
    const nodes = [n("c", "condition"), n("a", "input"), n("b", "llm"), n("d", "output")];
    const edges = [
      e("e1", "a", "c"),
      e("e2", "c", "d"),  // condition's first case
      e("e3", "b", "d"),
    ];
    const result = getBeforeNodes("d", nodes, edges);
    expect(result.map((x) => x.id).sort()).toEqual(["a", "b", "c"]);
  });
});

describe("useAvailableVarList", () => {
  it("returns upstream vars (does not include target's own vars)", () => {
    const nodes = [n("a", "input"), n("b", "llm")];
    const edges = [e("e1", "a", "b")];
    const { result } = renderHook(() => useAvailableVarList("b", nodes, edges));
    // Input has default 'value' var
    expect(result.current.length).toBeGreaterThan(0);
    expect(result.current.every((v) => v.nodeId !== "b")).toBe(true);
  });

  it("applies filterVar", () => {
    const nodes = [
      n("a", "input", { variables: [{ name: "x", type: "string" }, { name: "y", type: "number" }] }),
      n("b", "llm"),
    ];
    const edges = [e("e1", "a", "b")];
    const { result } = renderHook(() =>
      useAvailableVarList("b", nodes, edges, { filterVar: (v) => v.type === "string" })
    );
    expect(result.current.every((v) => v.type === "string")).toBe(true);
  });
});
