import api from "./auth";
import type { ApiResponse, PaginatedResponse } from "@/types/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:11335/api/v1";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type LlmCallStatus = "success" | "failure" | "partial";

export interface LLMCallLogItem {
  call_id: string;
  trace_id: string;
  call_type: string;
  call_index: number;
  tenant_id?: number;
  username?: string;
  conversation_id?: number;
  agent_id?: number;
  team_id?: number;
  team_member_id?: number;
  workflow_id?: number;
  workflow_run_id?: number;
  image_id?: number;
  model_type?: string;
  model_name: string;
  temperature?: number;
  user_message_preview?: string;
  response_preview?: string;
  input_chars?: number;
  output_chars?: number;
  token_usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  duration_ms?: number;
  first_token_latency_ms?: number;
  status: LlmCallStatus;
  error_type?: string;
  started_at: string;
  finished_at?: string;
  extra?: Record<string, unknown>;
}

export interface LLMCallLogDetail extends LLMCallLogItem {
  system_messages?: Array<Record<string, unknown>>;
  user_message?: string;
  messages?: Array<Record<string, unknown>>;
  tools?: Array<Record<string, unknown>>;
  extra_params?: Record<string, unknown>;
  response_content?: string;
  finish_reason?: string;
  tool_calls?: Array<Record<string, unknown>>;
  error_message?: string;
  request_ip?: string;
  user_agent?: string;
}

export interface LLMCallLogStats {
  calls_24h: number;
  errors_24h: number;
  total_tokens_24h: number;
  avg_duration_ms_24h: number;
  by_module_24h: Record<string, number>;
  by_model_24h: Record<string, number>;
}

export interface LLMCallLogListParams {
  page?: number;
  page_size?: number;
  module?: "chat" | "widget" | "agent_team" | "workflow" | "image_gen";
  call_type?: string;
  model_name?: string;
  status?: LlmCallStatus;
  conversation_id?: number;
  agent_id?: number;
  team_id?: number;
  workflow_id?: number;
  workflow_run_id?: number;
  trace_id?: string;
  start_time?: string;  // ISO
  end_time?: string;
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

export const llmCallLogsApi = {
  list: (params: LLMCallLogListParams = {}) =>
    api.get<PaginatedResponse<LLMCallLogItem>>("/logs/llm-calls", { params }),

  detail: (callId: string) =>
    api.get<ApiResponse<LLMCallLogDetail>>(`/logs/llm-calls/${callId}`),

  trace: (traceId: string) =>
    api.get<ApiResponse<LLMCallLogDetail[]>>(`/logs/llm-calls/trace/${traceId}`),

  stats: () =>
    api.get<ApiResponse<LLMCallLogStats>>("/logs/llm-calls/stats"),
};

// Silence unused warnings for API_BASE
void API_BASE;