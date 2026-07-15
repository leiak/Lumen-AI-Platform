"use client";
import { Pie, Column } from "@ant-design/charts";
import { Spin, Empty } from "antd";
import { useScreenStore } from "@/store/screen";
import { usePolling } from "@/hooks/usePolling";
import { screenApi } from "@/services/screen";
import { ErrorBoundary } from "./ErrorBoundary";

function KnowledgePanelInner() {
  const range = useScreenStore((s) => s.range);
  const intervalMs = useScreenStore((s) => s.intervalMs);
  const paused = useScreenStore((s) => s.paused);
  const { data, loading, error } = usePolling(
    () => screenApi.getKnowledge(range),
    { intervalMs, enabled: !paused, deps: [range] },
  );
  if (loading && !data) return <Spin />;
  if (error && !data) return <Empty description={error.message} />;
  if (!data) return <Spin />;
  return (
    <div className="panel" style={{ gridColumn: "span 4" }}>
      <div className="panel-title">知识库 / 文档</div>
      <div>知识库: {data.total_kbs} · 文档: {data.total_documents} · Chunk: {data.total_chunks}</div>
      <div>解析成功: {data.parse_success} · 失败: {data.parse_failed} · 嵌入失败: {data.embedding_failed}</div>
      <div style={{ marginTop: 8 }}>
        <Pie
          data={data.by_status.map((b) => ({ status: b.status, count: b.count }))}
          angleField="count" colorField="status" radius={0.85} innerRadius={0.5} height={200}
        />
      </div>
    </div>
  );
}
export function KnowledgePanel() { return <ErrorBoundary><KnowledgePanelInner /></ErrorBoundary>; }
