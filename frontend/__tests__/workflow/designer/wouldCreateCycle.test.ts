import { describe, expect, it } from "vitest";
import { wouldCreateCycle } from "@/app/dashboard/workflow/designer/hooks/wouldCreateCycle";

const N = (id: string) => ({ id });
const E = (source: string, target: string) => ({ source, target });

describe("wouldCreateCycle (M30 收口-C)", () => {
  it("self-loop is a cycle", () => {
    expect(wouldCreateCycle([N("a")], [], "a", "a")).toBe(true);
  });

  it("direct back-edge creates a cycle", () => {
    // a → b exists; adding b → a closes a loop.
    const nodes = [N("a"), N("b")];
    const edges = [E("a", "b")];
    expect(wouldCreateCycle(nodes, edges, "b", "a")).toBe(true);
  });

  it("transitive back-edge creates a cycle", () => {
    // a → b → c exists; adding c → a closes a loop.
    const nodes = [N("a"), N("b"), N("c")];
    const edges = [E("a", "b"), E("b", "c")];
    expect(wouldCreateCycle(nodes, edges, "c", "a")).toBe(true);
  });

  it("diamond shape is fine — closing one branch is NOT a cycle", () => {
    // a → b, a → c, b → d, c → d. Adding a → d just adds an extra
    // edge; the graph is still a DAG.
    const nodes = [N("a"), N("b"), N("c"), N("d")];
    const edges = [E("a", "b"), E("a", "c"), E("b", "d"), E("c", "d")];
    expect(wouldCreateCycle(nodes, edges, "a", "d")).toBe(false);
  });

  it("linear chain — no cycle", () => {
    const nodes = [N("a"), N("b"), N("c"), N("d")];
    const edges = [E("a", "b"), E("b", "c"), E("c", "d")];
    // Adding a new forward edge is fine.
    expect(wouldCreateCycle(nodes, edges, "a", "d")).toBe(false);
  });

  it("empty graph — first edge is fine", () => {
    expect(wouldCreateCycle([], [], "a", "b")).toBe(false);
  });
});
