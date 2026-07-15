"use client";

/**
 * M30 收口-B: useClipboard — internal clipboard for workflow nodes.
 *
 * Browsers' native `navigator.clipboard` doesn't fit our model:
 * we're copying serialized React Flow nodes + edges, not text.
 * The "clipboard" here is an in-memory module-level store scoped
 * to a single designer page (closing the tab clears it).
 *
 * Usage:
 *   const { copy, paste, hasContent } = useClipboard();
 *
 *   // On Ctrl+C:
 *   copy(selectedNodes, edges);
 *
 *   // On Ctrl+V:
 *   const cloned = paste(currentNodes, currentEdges, positionOffset);
 *   setNodes(cloned.newNodes);
 *   setEdges(cloned.newEdges);
 *
 * The cloned nodes get fresh ids (suffixed with `_copy_<random>`)
 * so the same paste operation can be repeated. Internal edges
 * (between two selected nodes) are also re-created with fresh ids
 * and re-pointed at the new node ids.
 *
 * Why module-level state: the clipboard is shared across hooks
 * (Ctrl+C on a different panel component should still be pasteable
 * on this one). A useState-in-hook would be lost between remounts.
 */

// Lightweight serialization — we only need the fields the backend
// cares about. `data` carries the per-type config the panel reads.
interface ClipboardNode {
  id: string;
  type: string;
  config: Record<string, any>;
  position: { x: number; y: number };
}

interface ClipboardEdge {
  source: string;
  target: string;
  sourceHandle?: string | null;
}

interface ClipboardPayload {
  nodes: ClipboardNode[];
  edges: ClipboardEdge[];
}

let payload: ClipboardPayload | null = null;

export function useClipboard() {
  const copy = (nodes: readonly any[], edges: readonly any[]) => {
    if (nodes.length === 0) {
      payload = null;
      return;
    }
    const idSet = new Set(nodes.map((n) => n.id));
    const internalEdges = edges.filter(
      (e) => idSet.has(e.source) && idSet.has(e.target)
    );
    payload = {
      nodes: nodes.map((n) => ({
        id: n.id,
        type: n.type,
        // Use `config` (the persisted shape) over `data` (the runtime
        // shape the panels mutate) — config is what the backend stores
        // and what a re-paste needs to re-create the node faithfully.
        config: (n.data?.config ?? n.config ?? {}) as Record<string, any>,
        position: { x: n.position?.x ?? 0, y: n.position?.y ?? 0 },
      })),
      edges: internalEdges.map((e) => ({
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle ?? null,
      })),
    };
  };

  const paste = (
    _currentNodes: readonly any[],
    _currentEdges: readonly any[],
    offset: { x: number; y: number } = { x: 40, y: 40 }
  ): {
    newNodes: any[];
    newEdges: any[];
  } | null => {
    if (!payload) return null;
    const idMap = new Map<string, string>();
    for (const n of payload.nodes) {
      // Random suffix so repeated pastes don't collide.
      const suffix = Math.random().toString(36).slice(2, 8);
      idMap.set(n.id, `${n.id}_copy_${suffix}`);
    }
    const newNodes = payload.nodes.map((n) => ({
      id: idMap.get(n.id)!,
      type: n.type,
      position: { x: n.position.x + offset.x, y: n.position.y + offset.y },
      data: { ...n.config, label: n.config.label || n.id },
    }));
    const newEdges = payload.edges.map((e, idx) => ({
      id: `e_copy_${Date.now()}_${idx}`,
      source: idMap.get(e.source)!,
      target: idMap.get(e.target)!,
      sourceHandle: e.sourceHandle ?? undefined,
    }));
    return { newNodes, newEdges };
  };

  const hasContent = (): boolean => payload !== null && payload.nodes.length > 0;

  const clear = () => {
    payload = null;
  };

  return { copy, paste, hasContent, clear };
}
