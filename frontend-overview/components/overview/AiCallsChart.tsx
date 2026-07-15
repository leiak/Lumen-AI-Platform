"use client";
import { Line, Column } from "@ant-design/charts";
import { Spin, Empty } from "antd";
import { useScreenStore } from "@/store/screen";
import { usePolling } from "@/hooks/usePolling";
import { screenApi, type ScreenGranularity } from "@/services/screen";
import { ErrorBoundary } from "./ErrorBoundary";

function AiCallsChartInner() {
  const range = useScreenStore((s) => s.range);
  const intervalMs = useScreenStore((s) => s.intervalMs);
  const paused = useScreenStore((s) => s.paused);
  const granularity: ScreenGranularity =
    range === "1h" ? "minute" : range === "30d" ? "day" : "hour";
  const { data, loading, error } = usePolling(
    () => screenApi.getAiCalls(range, granularity),
    { intervalMs, enabled: !paused, deps: [range] },
  );
  if (loading && !data) return <Spin />;
  if (error && !data) return <Empty description={error.message} />;
  if (!data) return <Spin />;
  return (
    <div className="panel" style={{ gridColumn: "span 8" }}>
      <div className="panel-title">AI 调用与错误数趋势</div>
      <Line
        data={data.series.flatMap((p) => ([
          { ts: p.ts, value: p.calls, metric: "calls" },
          { ts: p.ts, value: p.errors, metric: "errors" },
        ]))}
        xField="ts" yField="value" seriesField="metric" smooth height={240}
      />
      <div style={{ marginTop: 12 }} className="panel-title">按模型拆分</div>
      <Column data={data.by_model.map((m) => ({ model: m.model, calls: m.calls }))}
              xField="model" yField="calls" height={200} />
    </div>
  );
}

export function AiCallsChart() {
  return <ErrorBoundary><AiCallsChartInner /></ErrorBoundary>;
}
