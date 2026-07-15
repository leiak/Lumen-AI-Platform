import { useCallback, useEffect, useRef, useState } from "react";

export interface UsePollingOptions {
  intervalMs: number;       // 0 表示关闭
  enabled?: boolean;        // 总开关
  deps?: ReadonlyArray<unknown>;
}

export interface UsePollingResult<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
  lastUpdated: number | null;
}

export function usePolling<T>(
  fetcher: () => Promise<T>,
  { intervalMs, enabled = true, deps = [] }: UsePollingOptions,
): UsePollingResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const seqRef = useRef(0);

  const run = useCallback(async () => {
    const myId = ++seqRef.current;
    setLoading(true);
    try {
      const d = await fetcherRef.current();
      if (myId !== seqRef.current) return; // stale: a newer fetch has started
      setData(d);
      setError(null);
      setLastUpdated(Date.now());
    } catch (e) {
      if (myId !== seqRef.current) return; // stale: a newer fetch has started
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      if (myId === seqRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled || intervalMs <= 0) return;
    void run();
    const t = setInterval(() => void run(), intervalMs);
    return () => {
      clearInterval(t);
      seqRef.current++; // invalidate any in-flight fetches on unmount/dep change
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, intervalMs, ...deps]);

  return { data, loading, error, refetch: run, lastUpdated };
}
