"use client";
import { KpiCards } from "@/components/overview/KpiCards";
import { AiCallsChart } from "@/components/overview/AiCallsChart";
import { KnowledgePanel } from "@/components/overview/KnowledgePanel";
import { WorkflowPanel } from "@/components/overview/WorkflowPanel";
import { TenantUserPanel } from "@/components/overview/TenantUserPanel";

// Operations dashboard root. Renders anonymously; 5 panels fetched in parallel
// via the shared screenApi + usePolling hooks. Layout follows the
// .screen-grid / .panel CSS contract in app/globals.css.
export default function ScreenPage() {
  return (
    <>
      <KpiCards />
      <div className="screen-grid">
        <AiCallsChart />
        <KnowledgePanel />
      </div>
      <div className="screen-grid">
        <WorkflowPanel />
        <TenantUserPanel />
      </div>
    </>
  );
}
