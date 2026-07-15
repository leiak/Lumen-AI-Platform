"use client";
import { Column } from "@ant-design/charts";
import { Spin, Empty } from "antd";
import { useScreenStore } from "@/store/screen";
import { usePolling } from "@/hooks/usePolling";
import { screenApi } from "@/services/screen";
import { ErrorBoundary } from "./ErrorBoundary";

function WorkflowPanelInner() {
  const range = useScreenStore((s) => s.range);
  const intervalMs = useScreenStore((s) => s.intervalMs);
  const paused = useScreenStore((s) => s.paused);
  const { data, loading, error } = usePolling(
    () => screenApi.getWorkflows(range),
    { intervalMs, enabled: !paused, deps: [range] },
  );
  if (loading && !data) return <Spin />;
  if (error && !data) return <Empty description={error.message} />;
  if (!data) return <Spin />;
  return (
    <div className="panel" style={{ gridColumn: "span 6" }}>
      <div className="panel-title">工作流 / Agent 运行</div>
      <div>工作流: {data.total_workflows} · 运行: {data.total_runs} · 平均耗时 {data.avg_duration_ms} ms</div>
      <div>成功: {data.success} · 失败: {data.failed} · 取消: {data.cancelled}</div>
      <div style={{ marginTop: 8 }}>
        <Column
          data={data.by_node_type.map((n) => ({ type: n.node_type, runs: n.runs, errors: n.errors }))}
          xField="type" yField="runs" height={200}
        />
      </div>
    </div>
  );
}
export function WorkflowPanel() { return <ErrorBoundary><WorkflowPanelInner /></ErrorBoundary>; }
