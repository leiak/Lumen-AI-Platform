"use client";

/**
 * M30 收口-A: useDebouncedCallback — small debounce wrapper.
 *
 * Why: Panel editors fire ``onChange`` on every keystroke. For code /
 * HTTP / LLM / template_transform panels, the immediate onChange
 * causes a full re-render of the React Flow canvas (which is
 * expensive when the user is typing fast). We debounce so a burst
 * of keystrokes within ``delay`` ms collapses to a single commit.
 *
 * This is the simplest possible debounce: schedule a setTimeout on
 * every call, cancel the previous one. We don't use
 * ``use-debounce`` because it's a 1KB dep and the implementation
 * here is ~25 lines.
 *
 * Usage:
 *   const debouncedOnChange = useDebouncedCallback(
 *     (val) => onChange(val),
 *     200
 *   );
 *   <Input onChange={(e) => debouncedOnChange(e.target.value)} />
 */
import { useCallback, useEffect, useRef } from "react";

export function useDebouncedCallback<T extends (...args: any[]) => void>(
  fn: T,
  delay: number
): T {
  const fnRef = useRef(fn);
  // Keep the latest fn without retriggering the callback wrapper.
  useEffect(() => {
    fnRef.current = fn;
  }, [fn]);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cancel any pending timer on unmount so a stale commit doesn't
  // land after the component is gone.
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
    };
  }, []);

  return useCallback(
    ((...args: any[]) => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
      timerRef.current = setTimeout(() => {
        fnRef.current(...args);
      }, delay);
    }) as T,
    [delay]
  );
}
