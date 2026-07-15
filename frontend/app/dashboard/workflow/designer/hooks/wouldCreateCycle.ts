// M30 收口-C: wouldCreateCycle — pure helper used by the designer's
// onConnect validator. Split out from the page so the cycle check
// can be unit-tested without rendering the React Flow canvas.
//
// BFS from the proposed new edge's `target` node, following existing
// outgoing edges. If we reach `source`, the new edge would close
// a loop and the executor's BFS would loop forever (or the M30
// retry policy would repeatedly re-enqueue the same nodes).
//
// We do NOT consider the new edge itself in the BFS — only the
// pre-existing graph. That's the right semantics: "is the existing
// graph such that adding edge (source → target) creates a cycle?"

interface NodeLike {
  id: string;
}

interface EdgeLike {
  source: string;
  target: string;
}

export function wouldCreateCycle(
  nodes: readonly NodeLike[],
  edges: readonly EdgeLike[],
  source: string,
  target: string
): boolean {
  // Self-loop is a trivial cycle.
  if (source === target) return true;

  // Build the outgoing-edges adjacency for the existing graph.
  const out = new Map<string, string[]>();
  for (const e of edges) {
    const arr = out.get(e.source);
    if (arr) arr.push(e.target);
    else out.set(e.source, [e.target]);
  }

  // BFS from `target`. If we reach `source`, adding the new edge
  // would close a loop.
  const seen = new Set<string>([target]);
  const queue: string[] = [target];
  while (queue.length > 0) {
    const cur = queue.shift()!;
    if (cur === source) return true;
    for (const next of out.get(cur) ?? []) {
      if (!seen.has(next)) {
        seen.add(next);
        queue.push(next);
      }
    }
  }
  return false;
}
