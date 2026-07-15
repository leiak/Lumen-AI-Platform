"use client";
import { Spin, Empty } from "antd";
import CountUp from "react-countup";
import { useScreenStore } from "@/store/screen";
import { usePolling } from "@/hooks/usePolling";
import { screenApi } from "@/services/screen";
import { ErrorBoundary } from "./ErrorBoundary";

interface Card { label: string; value: number; suffix?: string; color?: string; }
const buildCards = (k: { total_tenants: number; active_tenants: number;
  total_users: number; active_users: number; total_agents: number; total_kbs: number;
  total_workflows: number; total_documents: number; total_chat_messages: number;
  ai_calls: number; ai_errors: number; ai_error_rate: number; }): Card[] => [
  { label: "租户数", value: k.total_tenants, color: "#1677ff" },
  { label: "活跃租户", value: k.active_tenants, color: "#13c2c2" },
  { label: "用户数", value: k.total_users, color: "#722ed1" },
  { label: "Agent 数", value: k.total_agents, color: "#52c41a" },
  { label: "工作流", value: k.total_workflows, color: "#fa8c16" },
  { label: "AI 调用 (24h)", value: k.ai_calls, color: "#eb2f96" },
];

function KpiCardsInner() {
  const range = useScreenStore((s) => s.range);
  const intervalMs = useScreenStore((s) => s.intervalMs);
  const paused = useScreenStore((s) => s.paused);
  const { data, loading, refetch, error } = usePolling(
    () => screenApi.getOverview(range),
    { intervalMs, enabled: !paused, deps: [range] },
  );
  if (loading && !data) return <Spin />;
  if (error && !data) return <Empty description={error.message} />;
  if (!data) return <Spin />;
  const cards = buildCards(data);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 12 }}>
      {cards.map((c) => (
        <div key={c.label} className="panel" style={{ textAlign: "center" }}>
          <div className="panel-title">{c.label}</div>
          <div style={{ fontSize: 28, color: c.color, fontWeight: 600 }}>
            <CountUp end={c.value} duration={0.8} preserveValue />
          </div>
        </div>
      ))}
    </div>
  );
}

export function KpiCards() {
  return <ErrorBoundary><KpiCardsInner /></ErrorBoundary>;
}
