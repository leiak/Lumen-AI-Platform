"use client";
import { Line } from "@ant-design/charts";
import { Spin, Empty, List } from "antd";
import { useScreenStore } from "@/store/screen";
import { usePolling } from "@/hooks/usePolling";
import { screenApi } from "@/services/screen";
import { ErrorBoundary } from "./ErrorBoundary";

function TenantUserPanelInner() {
  const range = useScreenStore((s) => s.range);
  const intervalMs = useScreenStore((s) => s.intervalMs);
  const paused = useScreenStore((s) => s.paused);
  const { data, loading, error } = usePolling(
    () => screenApi.getTenantsUsers(range),
    { intervalMs, enabled: !paused, deps: [range] },
  );
  if (loading && !data) return <Spin />;
  if (error && !data) return <Empty description={error.message} />;
  if (!data) return <Spin />;
  return (
    <div className="panel" style={{ gridColumn: "span 6" }}>
      <div className="panel-title">租户 / 用户</div>
      <Line
        data={[
          ...data.tenant_growth.map((p) => ({ ts: p.ts, value: p.count, metric: "tenants" })),
          ...data.user_growth.map((p) => ({ ts: p.ts, value: p.count, metric: "users" })),
        ]}
        xField="ts" yField="value" seriesField="metric" height={200}
      />
      <div style={{ marginTop: 8 }} className="panel-title">Top 活跃租户</div>
      <List
        size="small" dataSource={data.top_active_tenants}
        renderItem={(t) => <List.Item>Tenant#{t.tenant_id} · calls {t.calls}</List.Item>}
      />
    </div>
  );
}
export function TenantUserPanel() { return <ErrorBoundary><TenantUserPanelInner /></ErrorBoundary>; }
