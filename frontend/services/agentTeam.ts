import api from "./auth";
import type { ApiResponse, PaginatedResponse } from "@/types/api";
import type { Agent } from "@/types/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type RoutePolicy = "manager_decides" | "round_robin" | "first_match";

export interface AgentTeamMember {
  id: number;
  team_id: number;
  agent_id: number;
  role: string;
  priority: number;
  is_active: boolean;
  config?: Record<string, any> | null;
  created_at: string;
  agent_name?: string | null;
}

export interface AgentTeamRoute {
  id: number;
  team_id: number;
  agent_id: number;
  keywords: string[];
  priority: number;
}

export interface AgentTeam {
  id: number;
  name: string;
  description?: string | null;
  manager_agent_id: number;
  is_active: boolean;
  route_policy: RoutePolicy;
  aggregator_prompt?: string | null;
  config?: Record<string, any> | null;
  tenant_id: number;
  created_at: string;
  members: AgentTeamMember[];
  routes: AgentTeamRoute[];
}

export interface AgentTeamSummary {
  id: number;
  name: string;
  description?: string | null;
  manager_agent_id: number;
  is_active: boolean;
  route_policy: RoutePolicy;
  aggregator_prompt?: string | null;
  config?: Record<string, any> | null;
  tenant_id: number;
  created_at: string;
  member_count: number;
}

export interface WorkerOutput {
  member_id?: number | null;
  agent_id: number;
  agent_name?: string | null;
  role?: string | null;
  response: string;
}

export interface TeamChatResponse {
  team_id: number;
  final_answer: string;
  manager_reasoning?: string | null;
  routing_decision?: number[] | null;
  worker_outputs: WorkerOutput[];
  policy_used: RoutePolicy;
  // Echoed back so the frontend can update its sidebar selection
  // (first turn creates a new conv, subsequent turns reuse it).
  conversation_id: number;
}

/**
 * Lightweight shape returned by the team-conversation list endpoint.
 * Mirrors `AgentTeamConversationResponse` in `schemas/agent_team.py`.
 *
 * The `metadata` field on `Message` is the JSON-decoded
 * `msg_metadata` column from `messages`; for assistant messages the
 * backend writes `{routing_decision, worker_outputs, policy_used,
 * manager_reasoning}` so the frontend can rebuild the worker
 * folding region without a second round-trip.
 */
export interface TeamConversation {
  id: number;
  title?: string | null;
  team_id?: number | null;
  user_id: number;
  created_at: string;
  updated_at: string;
}

export interface TeamMessageMetadata {
  routing_decision?: number[] | null;
  worker_outputs?: WorkerOutput[] | null;
  policy_used?: RoutePolicy | null;
  manager_reasoning?: string | null;
}

export interface TeamMessage {
  id: number;
  conversation_id: number;
  role: "user" | "assistant" | "system";
  content: string;
  metadata?: TeamMessageMetadata | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

export const agentTeamApi = {
  list: (page = 1, pageSize = 10) =>
    api.get<PaginatedResponse<AgentTeamSummary>>(
      `/agent-teams/?page=${page}&page_size=${pageSize}`,
    ),
  get: (id: number) =>
    api.get<ApiResponse<AgentTeam>>(`/agent-teams/${id}`),
  create: (data: {
    name: string;
    description?: string;
    manager_agent_id: number;
    is_active?: boolean;
    route_policy?: RoutePolicy;
    aggregator_prompt?: string;
    config?: Record<string, any>;
    members?: Array<{
      agent_id: number;
      role?: string;
      priority?: number;
      is_active?: boolean;
    }>;
    routes?: Array<{ agent_id: number; keywords: string[]; priority?: number }>;
  }) => api.post<ApiResponse<AgentTeam>>("/agent-teams/", data),
  update: (id: number, data: Partial<AgentTeam> & { members?: any[]; routes?: any[] }) =>
    api.put<ApiResponse<AgentTeam>>(`/agent-teams/${id}`, data),
  remove: (id: number) => api.delete<ApiResponse<any>>(`/agent-teams/${id}`),

  addMember: (
    teamId: number,
    data: { agent_id: number; role?: string; priority?: number; is_active?: boolean },
  ) =>
    api.post<ApiResponse<AgentTeamMember>>(
      `/agent-teams/${teamId}/members`,
      data,
    ),
  removeMember: (teamId: number, memberId: number) =>
    api.delete<ApiResponse<any>>(
      `/agent-teams/${teamId}/members/${memberId}`,
    ),

  chat: (
    teamId: number,
    message: string,
    conversationId?: number,
    opts?: { route_policy?: RoutePolicy; member_ids?: number[] },
  ) =>
    api.post<ApiResponse<TeamChatResponse>>(`/agent-teams/${teamId}/chat`, {
      message,
      // Backend pulls prior history from the DB when conversation_id is
      // set; the legacy `history` field is dropped intentionally — see
      // AgentTeamChatRequest schema note.
      conversation_id: conversationId,
      route_policy: opts?.route_policy,
      member_ids: opts?.member_ids,
    }),

  // ---- Team conversations (history) ----
  // Mirrors the single-agent chat history endpoints in services/chat.ts.
  // All four are scoped to a specific team — the backend's
  // verify_team_conversation helper enforces the team binding on every
  // read/write so cross-team IDOR isn't possible.

  listConversations: (teamId: number) =>
    api.get<ApiResponse<TeamConversation[]>>(
      `/agent-teams/${teamId}/conversations`,
    ),

  createConversation: (teamId: number, title?: string) =>
    api.post<ApiResponse<TeamConversation>>(
      `/agent-teams/${teamId}/conversations`,
      { title },
    ),

  getMessages: (teamId: number, conversationId: number) =>
    api.get<ApiResponse<TeamMessage[]>>(
      `/agent-teams/${teamId}/conversations/${conversationId}/messages`,
    ),

  deleteConversation: (teamId: number, conversationId: number) =>
    api.delete<ApiResponse<null>>(
      `/agent-teams/${teamId}/conversations/${conversationId}`,
    ),
};

export type { Agent };
