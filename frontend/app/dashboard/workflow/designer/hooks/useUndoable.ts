"use client";

/**
 * M30d: useUndoable — small undo/redo stack for the workflow designer.
 *
 * Wrap any stateful set with the returned ``push``:
 *
 *   const { state, set, push, undo, redo, canUndo, canRedo } =
 *     useUndoable<Node[]>(initialNodes);
 *
 *   // direct set (no history entry, e.g. dragging a node)
 *   set(nodesRef.current);
 *
 *   // push a new history entry (e.g. after a user-driven edit)
 *   push(newNodes);
 *
 *   // Ctrl+Z → undo(), Ctrl+Shift+Z → redo()
 *
 * The stack is bounded to ``MAX_HISTORY`` (50) so a long edit
 * session doesn't blow up the browser. Older entries fall off the
 * bottom.
 *
 * Why 50: enough for a typical "add 5 nodes, tweak each" flow
 * without holding the entire history of a 200-node workflow in
 * memory. The number is a magic constant; the user can override by
 * passing a different ``maxSize`` to the hook.
 */
import { useCallback, useRef, useState } from "react";

const MAX_HISTORY = 50;

export function useUndoable<T>(initial: T, maxSize: number = MAX_HISTORY) {
  // We hold the "current" value as React state (so the UI re-renders
  // when the value changes) but keep the undo/redo stack in a ref to
  // avoid re-renders on every push.
  const [state, setState] = useState<T>(initial);
  const historyRef = useRef<{
    past: T[];
    future: T[];
  }>({ past: [], future: [] });

  const push = useCallback(
    (next: T) => {
      // Snapshot the previous state, then set.
      setState((prev) => {
        // Don't push if the value is structurally identical to the
        // current top of the history (avoids duplicate entries when
        // a user clicks the same button twice).
        if (historyRef.current.past.length > 0) {
          const top = historyRef.current.past[historyRef.current.past.length - 1];
          if (Object.is(top, prev)) return prev;
        }
        const newPast = [...historyRef.current.past, prev];
        // Drop the oldest entry when we exceed the cap.
        if (newPast.length > maxSize) newPast.shift();
        historyRef.current = {
          past: newPast,
          future: [],  // a new edit invalidates the redo stack
        };
        return next;
      });
    },
    [maxSize]
  );

  const set = useCallback((next: T) => {
    // Direct set: no history entry. Used for transient updates
    // (drag, hover).
    setState(next);
  }, []);

  const undo = useCallback(() => {
    setState((prev) => {
      const last = historyRef.current.past[historyRef.current.past.length - 1];
      if (last === undefined) return prev;
      historyRef.current = {
        past: historyRef.current.past.slice(0, -1),
        future: [prev, ...historyRef.current.future],
      };
      return last;
    });
  }, []);

  const redo = useCallback(() => {
    setState((prev) => {
      const next = historyRef.current.future[0];
      if (next === undefined) return prev;
      historyRef.current = {
        past: [...historyRef.current.past, prev],
        future: historyRef.current.future.slice(1),
      };
      return next;
    });
  }, []);

  const canUndo = historyRef.current.past.length > 0;
  const canRedo = historyRef.current.future.length > 0;

  const reset = useCallback((next: T) => {
    setState(next);
    historyRef.current = { past: [], future: [] };
  }, []);

  return {
    state,
    set,
    push,
    undo,
    redo,
    canUndo,
    canRedo,
    reset,
  };
}
