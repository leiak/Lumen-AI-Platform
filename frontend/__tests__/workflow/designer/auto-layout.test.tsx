import { describe, expect, it } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAutoLayout } from "@/app/dashboard/workflow/designer/hooks/useAutoLayout";

interface MockNode {
  id: string;
  position: { x: number; y: number };
}

describe("useAutoLayout (M30d)", () => {
  it("returns a stable autoLayout function", () => {
    const { result } = renderHook(() => useAutoLayout());
    expect(typeof result.current.autoLayout).toBe("function");
  });

  it("returns an empty array for an empty input", () => {
    const { result } = renderHook(() => useAutoLayout());
    const out = result.current.autoLayout<MockNode>([], []);
    expect(out).toEqual([]);
  });

  it("re-positions nodes so they're not all stacked at (0,0)", () => {
    const { result } = renderHook(() => useAutoLayout());
    // 5 nodes + 4 edges (linear): a -> b -> c -> d -> e
    const nodes: MockNode[] = [
      { id: "a", position: { x: 0, y: 0 } },
      { id: "b", position: { x: 0, y: 0 } },
      { id: "c", position: { x: 0, y: 0 } },
      { id: "d", position: { x: 0, y: 0 } },
      { id: "e", position: { x: 0, y: 0 } },
    ];
    const edges = [
      { source: "a", target: "b" },
      { source: "b", target: "c" },
      { source: "c", target: "d" },
      { source: "d", target: "e" },
    ];
    const out = result.current.autoLayout<MockNode>(nodes, edges);
    // Every node should have a distinct position (dagre gives each
    // node a unique rank).
    const positions = out.map((n) => `${n.position.x},${n.position.y}`);
    const unique = new Set(positions);
    expect(unique.size).toBe(5);
  });

  it("preserves node ids and ordering", () => {
    const { result } = renderHook(() => useAutoLayout());
    const nodes: MockNode[] = [
      { id: "x", position: { x: 0, y: 0 } },
      { id: "y", position: { x: 0, y: 0 } },
    ];
    const out = result.current.autoLayout<MockNode>(nodes, [
      { source: "x", target: "y" },
    ]);
    expect(out.map((n) => n.id)).toEqual(["x", "y"]);
  });

  it("supports LR (left-to-right) direction", () => {
    const { result } = renderHook(() => useAutoLayout());
    const nodes: MockNode[] = [
      { id: "a", position: { x: 0, y: 0 } },
      { id: "b", position: { x: 0, y: 0 } },
    ];
    const tb = result.current.autoLayout<MockNode>(
      nodes, [{ source: "a", target: "b" }], "TB"
    );
    const lr = result.current.autoLayout<MockNode>(
      nodes, [{ source: "a", target: "b" }], "LR"
    );
    // In TB, b is below a (larger y). In LR, b is right of a (larger x).
    expect(tb[1].position.y).toBeGreaterThan(tb[0].position.y);
    expect(lr[1].position.x).toBeGreaterThan(lr[0].position.x);
  });
});
