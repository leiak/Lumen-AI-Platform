import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { usePolling } from "@/hooks/usePolling";

describe("usePolling", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("fetches immediately on mount when enabled", async () => {
    const fetcher = vi.fn().mockResolvedValue("ok");
    const { result } = renderHook(() =>
      usePolling(fetcher, { intervalMs: 1000, enabled: true }),
    );
    await act(async () => { await Promise.resolve(); });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(result.current.data).toBe("ok");
  });

  it("polls at intervalMs", async () => {
    const fetcher = vi.fn().mockResolvedValue("v");
    renderHook(() => usePolling(fetcher, { intervalMs: 5000, enabled: true }));
    await act(async () => { await Promise.resolve(); });
    expect(fetcher).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(5000); });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("does not poll when enabled=false", async () => {
    const fetcher = vi.fn().mockResolvedValue("v");
    renderHook(() => usePolling(fetcher, { intervalMs: 5000, enabled: false }));
    await act(async () => { vi.advanceTimersByTime(10000); });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("does not poll when intervalMs=0", async () => {
    const fetcher = vi.fn().mockResolvedValue("v");
    renderHook(() => usePolling(fetcher, { intervalMs: 0, enabled: true }));
    await act(async () => { vi.advanceTimersByTime(10000); });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("refetch triggers manual fetch", async () => {
    const fetcher = vi.fn().mockResolvedValue("v");
    const { result } = renderHook(() =>
      usePolling(fetcher, { intervalMs: 0, enabled: true }),
    );
    await act(async () => { await result.current.refetch(); });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("captures errors", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() =>
      usePolling(fetcher, { intervalMs: 0, enabled: true }),
    );
    await act(async () => { await result.current.refetch(); });
    expect(result.current.error?.message).toBe("boom");
  });

  it("re-fetches when deps change", async () => {
    const fetcher = vi.fn().mockResolvedValue("v");
    const { rerender } = renderHook(
      ({ id }: { id: number }) =>
        usePolling(fetcher, { intervalMs: 1000, enabled: true, deps: [id] }),
      { initialProps: { id: 1 } },
    );
    // mount: effect fires run() once
    await act(async () => { await Promise.resolve(); });
    expect(fetcher).toHaveBeenCalledTimes(1);
    // deps change: effect re-runs and fires run() once more
    rerender({ id: 2 });
    await act(async () => { await Promise.resolve(); });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("stops polling when enabled flips true → false", async () => {
    const fetcher = vi.fn().mockResolvedValue("v");
    const { rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) =>
        usePolling(fetcher, { intervalMs: 1000, enabled }),
      { initialProps: { enabled: true } },
    );
    await act(async () => { await Promise.resolve(); });
    expect(fetcher).toHaveBeenCalledTimes(1);
    rerender({ enabled: false });
    await act(async () => { vi.advanceTimersByTime(5000); });
    // no further fetches after the flip
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("cleans up the interval on unmount", async () => {
    const fetcher = vi.fn().mockResolvedValue("v");
    const { unmount } = renderHook(() =>
      usePolling(fetcher, { intervalMs: 1000, enabled: true }),
    );
    await act(async () => { await Promise.resolve(); });
    expect(fetcher).toHaveBeenCalledTimes(1);
    unmount();
    await act(async () => { vi.advanceTimersByTime(5000); });
    // unmount cleared the interval; no more fetches
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("clears a prior error on a successful fetch", async () => {
    const fetcher = vi.fn()
      .mockRejectedValueOnce(new Error("first fails"))
      .mockResolvedValueOnce("ok");
    const { result } = renderHook(() =>
      usePolling(fetcher, { intervalMs: 0, enabled: true }),
    );
    await act(async () => { await result.current.refetch(); });
    expect(result.current.error?.message).toBe("first fails");
    await act(async () => { await result.current.refetch(); });
    expect(result.current.error).toBeNull();
    expect(result.current.data).toBe("ok");
  });
});
