// frontend/components/workflow/_base/hooks/useAvailableVarList.ts
import { useMemo } from "react";
import type { WorkflowNode, WorkflowEdge } from "@/services/workflow";
import { formatItem } from "../variable/utils";
import type { Var } from "../variable/types";

/**
 * Reverse BFS: list all upstream nodes that can reach `nodeId`.
 * P1: does NOT prune by condition branches (cross-branch vars appear; rely on filterVar
 *      to gate by type). P3 upgrades to per-sourceHandle pruning.
 */
export function getBeforeNodes(
  nodeId: string,
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
): WorkflowNode[] {
  const reverseAdj = new Map<string, string[]>();
  edges.forEach((e) => {
    if (!reverseAdj.has(e.target)) reverseAdj.set(e.target, []);
    reverseAdj.get(e.target)!.push(e.source);
  });
  const visited = new Set<string>();
  const queue: string[] = [nodeId];
  const result: WorkflowNode[] = [];
  while (queue.length) {
    const cur = queue.shift()!;
    if (visited.has(cur)) continue;
    visited.add(cur);
    const node = nodes.find((n) => n.id === cur);
    if (node && cur !== nodeId) result.push(node);
    for (const src of reverseAdj.get(cur) ?? []) {
      queue.push(src);
    }
  }
  return result;
}

export interface UseAvailableVarListOpts {
  filterVar?: (v: Var) => boolean;
}

export function useAvailableVarList(
  nodeId: string,
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  opts?: UseAvailableVarListOpts,
): Var[] {
  return useMemo(() => {
    const before = getBeforeNodes(nodeId, nodes, edges);
    const vars = before.flatMap((n) => formatItem(n));
    return opts?.filterVar ? vars.filter(opts.filterVar) : vars;
  }, [nodeId, nodes, edges, opts?.filterVar]);
}
