import api from "./api";

export type ScreenRange = "1h" | "24h" | "7d" | "30d";
export type ScreenGranularity = "minute" | "hour" | "day";

export interface KpiOverview {
  range: ScreenRange;
  total_tenants: number;
  active_tenants: number;
  total_users: number;
  active_users: number;
  total_agents: number;
  total_kbs: number;
  total_workflows: number;
  total_documents: number;
  total_chunks: number;
  total_chat_messages: number;
  ai_calls: number;
  ai_errors: number;
  ai_error_rate: number;
  top_tenants: { tenant_id: number; ai_calls: number }[];
  data_source_note: string;
}

export interface AiCallsResp {
  series: { ts: string; calls: number; errors: number; avg_latency_ms: number; p95_latency_ms: number | null }[];
  by_model: { model: string; calls: number; errors: number; avg_latency_ms: number }[];
}

export interface KnowledgeResp {
  total_kbs: number; total_documents: number; total_chunks: number;
  parse_success: number; parse_failed: number; embedding_failed: number;
  by_status: { status: string; count: number }[];
}

export interface WorkflowsResp {
  total_workflows: number; total_runs: number; success: number; failed: number; cancelled: number;
  avg_duration_ms: number; by_node_type: { node_type: string; runs: number; errors: number }[];
}

export interface TenantsUsersResp {
  tenant_growth: { ts: string; count: number }[];
  user_growth: { ts: string; count: number }[];
  top_active_tenants: { tenant_id: number; calls: number; messages: number }[];
}

const wrap = <T>(p: Promise<{ data: { code: number; data: T } }>) =>
  p.then((r) => r.data.data);

export const screenApi = {
  getOverview: (range: ScreenRange) => wrap<KpiOverview>(api.get("/screen/overview", { params: { range } })),
  getAiCalls: (range: ScreenRange, granularity: ScreenGranularity) =>
    wrap<AiCallsResp>(api.get("/screen/ai-calls", { params: { range, granularity } })),
  getKnowledge: (range: ScreenRange) => wrap<KnowledgeResp>(api.get("/screen/knowledge", { params: { range } })),
  getWorkflows: (range: ScreenRange) => wrap<WorkflowsResp>(api.get("/screen/workflows", { params: { range } })),
  getTenantsUsers: (range: ScreenRange) => wrap<TenantsUsersResp>(api.get("/screen/tenants-users", { params: { range } })),
};
