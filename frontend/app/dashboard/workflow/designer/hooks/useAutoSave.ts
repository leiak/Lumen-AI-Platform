"use client";

/**
 * useAutoSave — debounced auto-save for the workflow designer.
 *
 * M30d 2.0 (2026-09-07): triggers the supplied ``saveFn`` 300ms after
 * the watched deps (typically ``nodes`` + ``edges``) stop changing.
 *
 * Why this exists:
 *  - User moves a node on the canvas. Every drag step fires React Flow's
 *    ``onNodesChange`` and re-renders the page. Without debouncing, that
 *    would also fire a PUT /workflows/{id} per drag tick.
 *  - The 300ms window is the AntD/MUI sweet spot — short enough that the
 *    "已保存" feedback feels instant, long enough that quick successive
 *    edits coalesce into a single save.
 *
 * Contract:
 *  - The hook owns the timer; it cleans up on unmount + dep change.
 *  - ``saveFn`` is responsible for its own status reporting — the hook
 *    does not return status. The designer keeps using its existing
 *    ``saveStatus`` state machine driven by ``handleSave``.
 *  - The first render does NOT fire a save (the workflow hasn't been
 *    touched yet — the user just opened it).
 *  - A ``flushRef`` lets the parent fire an immediate save (e.g. on tab
 *    blur or before navigating away) so the debounce isn't lost.
 */
import { useEffect, useRef } from "react";

export interface UseAutoSaveOptions {
  /** Debounce delay in ms. Default 300. */
  delayMs?: number;
  /** Set to false to disable auto-save entirely. */
  enabled?: boolean;
}

export function useAutoSave<T>(
  deps: T,
  saveFn: () => Promise<void> | void,
  options: UseAutoSaveOptions = {},
): { flush: () => void } {
  const { delayMs = 300, enabled = true } = options;
  const isFirstRun = useRef(true);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const flushRef = useRef<() => void>(() => {});

  // Expose a flush() so the parent can fire the save right now
  // (e.g. before unmount) without waiting for the debounce.
  useEffect(() => {
    flushRef.current = () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      // Fire-and-forget — the designer's handleSave already updates
      // saveStatus, lastSavedAt, etc. on its own.
      void saveFn();
    };
    // saveFn identity may change on re-render; we want the latest one
  }, [saveFn]);

  useEffect(() => {
    if (!enabled) {
      // Even when disabled, mark "first run" as consumed so that flipping
      // enabled→true after the mount doesn't get skipped — that would
      // look like the hook silently swallowing the very first edit.
      isFirstRun.current = false;
      return;
    }
    // Skip the first run — opening a workflow shouldn't auto-save.
    if (isFirstRun.current) {
      isFirstRun.current = false;
      return;
    }
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
    }
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      void saveFn();
    }, delayMs);
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [deps, enabled, delayMs, saveFn]);

  return {
    flush: () => flushRef.current(),
  };
}
