"use client";

/**
 * M30d: useAutoLayout — given the current nodes + edges, compute a
 * new set of node positions using dagre's layered layout. The hook
 * is a thin React-friendly wrapper over the underlying dagre graph;
 * the caller passes nodes / edges in, gets a new nodes array back
 * with the ``position`` field updated to dagre's layout.
 *
 * Why dagre: it's the de-facto library for layered DAG layout. The
 * rendered output is what users expect from flow-chart editors
 * (input → process → output, top-to-bottom, no edge crossings).
 * The package is ~30KB and ships as pure JS — no canvas / DOM
 * dependencies.
 *
 * Usage:
 *   const { autoLayout, isReady } = useAutoLayout();
 *   const newNodes = autoLayout(nodes, edges, "TB");
 *   setNodes(newNodes);
 *
 * "TB" = top-to-bottom (default); "LR" = left-to-right.
 */
import { useCallback, useState } from "react";
// @dagrejs/dagre 3.0+ ships first-class TS types; the older
// 1.x line didn't, hence the previous ts-expect-error. dagre 3.0
// is what we resolved to in package.json — the import is typed.
import * as dagre from "@dagrejs/dagre";

export type LayoutDirection = "TB" | "LR";

interface Positioned {
  id: string;
  position: { x: number; y: number };
}

interface EdgeLike {
  source: string;
  target: string;
}

export function useAutoLayout() {
  const [isReady, setIsReady] = useState(true);

  const autoLayout = useCallback(
    <T extends Positioned>(
      nodes: readonly T[],
      edges: readonly EdgeLike[],
      direction: LayoutDirection = "TB"
    ): T[] => {
      if (nodes.length === 0) return [];

      // Build a fresh dagre graph. We re-create it every call so a
      // stale layout from a prior invocation never leaks.
      const g = new dagre.graphlib.Graph();
      g.setGraph({
        rankdir: direction,
        // Reasonable defaults for a designer canvas. Users can tweak
        // by passing options through later; for now these match
        // dagre's default 50px node size + ranksep.
        nodesep: 50,
        ranksep: 80,
        marginx: 20,
        marginy: 20,
      });
      g.setDefaultEdgeLabel(() => ({}));

      for (const n of nodes) {
        g.setNode(n.id, { width: 200, height: 100 });
      }
      for (const e of edges) {
        g.setEdge(e.source, e.target);
      }

      dagre.layout(g);

      // Project the new positions back onto the input nodes so
      // callers keep their own data + types intact.
      return nodes.map((n) => {
        const dn = g.node(n.id);
        if (!dn) return n;
        // dagre returns the *center* of the node; React Flow wants
        // the top-left. We subtract half the width/height (which
        // we set above) to get the top-left coordinate.
        return {
          ...n,
          position: { x: dn.x - 100, y: dn.y - 50 },
        };
      });
    },
    []
  );

  return { autoLayout, isReady, setIsReady };
}
