import api from "./auth";
import type { ApiResponse } from "@/types/api";

export interface StatsData {
  agent_count: number;
  knowledge_count: number;
  conversation_count: number;
  workflow_count: number;
}

export const dashboardApi = {
  getStats: () => api.get<ApiResponse<StatsData>>("/dashboard/stats"),
};