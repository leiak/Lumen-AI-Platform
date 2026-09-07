/**
 * M30d 2.0 (2026-09-07): useAutoSave hook tests.
 *
 * Covers the 4 cases called out in 2.0 spec A8:
 *  - debounce coalesces rapid edits into one save
 *  - the timer cleans up on unmount
 *  - flush() fires immediately
 *  - first render does NOT auto-save
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAutoSave } from "@/app/dashboard/workflow/designer/hooks/useAutoSave";

describe("useAutoSave (M30d 2.0)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not save on first render (just opened a workflow)", async () => {
    const saveFn = vi.fn().mockResolvedValue(undefined);
    const { rerender } = renderHook(
      ({ value }) => useAutoSave(value, saveFn, { delayMs: 300 }),
      { initialProps: { value: { n: 0 } } },
    );
    // Advance past the debounce window
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(saveFn).not.toHaveBeenCalled();
    rerender({ value: { n: 1 } });
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(saveFn).toHaveBeenCalledTimes(1);
  });

  it("debounces rapid successive edits into a single save", async () => {
    const saveFn = vi.fn().mockResolvedValue(undefined);
    const { rerender } = renderHook(
      ({ value }) => useAutoSave(value, saveFn, { delayMs: 300 }),
      { initialProps: { value: { n: 0 } } },
    );
    // 5 quick edits within the debounce window — should coalesce
    for (let i = 1; i <= 5; i++) {
      rerender({ value: { n: i } });
      await act(async () => {
        vi.advanceTimersByTime(50);
      });
    }
    expect(saveFn).not.toHaveBeenCalled();
    // Wait past the debounce window
    await act(async () => {
      vi.advanceTimersByTime(400);
    });
    expect(saveFn).toHaveBeenCalledTimes(1);
  });

  it("cleans up the timer on unmount", async () => {
    const saveFn = vi.fn().mockResolvedValue(undefined);
    const { unmount, rerender } = renderHook(
      ({ value }) => useAutoSave(value, saveFn, { delayMs: 300 }),
      { initialProps: { value: { n: 0 } } },
    );
    rerender({ value: { n: 1 } });
    unmount();
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(saveFn).not.toHaveBeenCalled();
  });

  it("flush() fires immediately, bypassing debounce", async () => {
    const saveFn = vi.fn().mockResolvedValue(undefined);
    const { result, rerender } = renderHook(
      ({ value }) => useAutoSave(value, saveFn, { delayMs: 300 }),
      { initialProps: { value: { n: 0 } } },
    );
    rerender({ value: { n: 1 } });
    // Don't wait the debounce — flush now
    await act(async () => {
      result.current.flush();
      await Promise.resolve();
    });
    expect(saveFn).toHaveBeenCalledTimes(1);
  });

  it("skips saving when enabled is false", async () => {
    const saveFn = vi.fn().mockResolvedValue(undefined);
    const { rerender } = renderHook(
      ({ value, enabled }) =>
        useAutoSave(value, saveFn, { delayMs: 300, enabled }),
      { initialProps: { value: { n: 0 }, enabled: false as boolean } },
    );
    rerender({ value: { n: 1 }, enabled: false });
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(saveFn).not.toHaveBeenCalled();
    // Flip enabled → next edit should save
    rerender({ value: { n: 2 }, enabled: true });
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(saveFn).toHaveBeenCalledTimes(1);
  });
});
