import { describe, expect, it, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useClipboard } from "@/app/dashboard/workflow/designer/hooks/useClipboard";

// A small graph: a → b → c, with a side edge b → d (so d is in the
// graph but not selected — its edge should NOT be cloned on paste).
const sampleNodes: any[] = [
  { id: "a", type: "input", position: { x: 0, y: 0 },
    data: { label: "Input", config: { title: "Input" } } },
  { id: "b", type: "llm", position: { x: 200, y: 0 },
    data: { label: "LLM", config: { title: "LLM", prompt: "hi" } } },
  { id: "c", type: "output", position: { x: 400, y: 0 },
    data: { label: "Output", config: { title: "Output" } } },
  { id: "d", type: "output", position: { x: 400, y: 100 },
    data: { label: "Output2", config: { title: "Output2" } } },
];
const sampleEdges: any[] = [
  { id: "e1", source: "a", target: "b" },
  { id: "e2", source: "b", target: "c" },
  { id: "e3", source: "b", target: "d" },
];

describe("useClipboard (M30 收口-B)", () => {
  beforeEach(() => {
    // Reset module-level state by clearing after each test.
    const { result } = renderHook(() => useClipboard());
    act(() => result.current.clear());
  });

  it("has no content initially", () => {
    const { result } = renderHook(() => useClipboard());
    expect(result.current.hasContent()).toBe(false);
    expect(result.current.paste([], [])).toBeNull();
  });

  it("copy() records selected nodes; paste() returns new ids + positions offset", () => {
    const { result } = renderHook(() => useClipboard());
    act(() => {
      result.current.copy(
        sampleNodes.filter((n) => ["a", "b", "c"].includes(n.id)),
        sampleEdges
      );
    });
    expect(result.current.hasContent()).toBe(true);

    let cloned: { newNodes: any[]; newEdges: any[] } | null = null;
    act(() => {
      cloned = result.current.paste(sampleNodes, sampleEdges, { x: 50, y: 30 });
    });
    expect(cloned).not.toBeNull();
    expect(cloned!.newNodes.length).toBe(3);
    // New ids are unique and different from originals.
    const newIds = cloned!.newNodes.map((n) => n.id);
    expect(new Set(newIds).size).toBe(3);
    for (const id of newIds) {
      expect(id).not.toMatch(/^(a|b|c)$/);
      expect(id).toMatch(/_copy_/);
    }
    // Positions are offset by 50,30.
    expect(cloned!.newNodes[0].position).toEqual({ x: 50, y: 30 });
    expect(cloned!.newNodes[1].position).toEqual({ x: 250, y: 30 });
    expect(cloned!.newNodes[2].position).toEqual({ x: 450, y: 30 });
  });

  it("paste() only re-points INTERNAL edges (drops edges to non-selected nodes)", () => {
    const { result } = renderHook(() => useClipboard());
    act(() => {
      // Select only a, b. d is NOT selected.
      result.current.copy(
        sampleNodes.filter((n) => ["a", "b"].includes(n.id)),
        sampleEdges
      );
    });

    let cloned: { newNodes: any[]; newEdges: any[] } | null = null;
    act(() => {
      cloned = result.current.paste(sampleNodes, sampleEdges);
    });
    // Edges in clipboard: e1 (a→b, internal) + e3 (b→d, NOT internal
    // because d is not selected). So only e1 should be cloned.
    expect(cloned!.newEdges.length).toBe(1);
    // Source and target ids are remapped to the new ids.
    const aNewId = cloned!.newNodes.find((n) => n.id.includes("a"))!.id;
    const bNewId = cloned!.newNodes.find((n) => n.id.includes("b"))!.id;
    expect(cloned!.newEdges[0].source).toBe(aNewId);
    expect(cloned!.newEdges[0].target).toBe(bNewId);
  });

  it("repeated paste produces unique ids (no collisions)", () => {
    const { result } = renderHook(() => useClipboard());
    act(() => {
      result.current.copy([sampleNodes[0]], []);
    });

    let first: { newNodes: any[] } | null = null;
    let second: { newNodes: any[] } | null = null;
    act(() => {
      first = result.current.paste([], []);
    });
    act(() => {
      second = result.current.paste([], []);
    });
    // Two separate paste calls should produce different ids (the
    // random suffix in the id map ensures this even if the user
    // pastes the same source twice without modifying it).
    expect(first!.newNodes[0].id).not.toBe(second!.newNodes[0].id);
  });
});
