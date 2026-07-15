import api from "./auth";
import type {
  Agent,
  AgentCreatePayload,
  AgentUpdatePayload,
  ApiResponse,
} from "@/types/api";

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

// Mirrors the backend MemoryPolicy / ToolChoiceMode enums (Task 8).
export const MEMORY_POLICIES = [
  { value: "sliding_window", label: "滑动窗口" },
  { value: "token_limit", label: "Token 限制" },
  { value: "semantic_compression", label: "语义压缩" },
  { value: "none", label: "不使用记忆" },
] as const;

export const TOOL_CHOICE_MODES = [
  { value: "auto", label: "自动 (Auto)" },
  { value: "required", label: "必须调用 (Required)" },
  { value: "none", label: "不调用工具 (None)" },
  { value: "specific", label: "指定工具 (Specific)" },
] as const;

export type { AgentCreatePayload, AgentUpdatePayload };

export const agentApi = {
  list: (page = 1, pageSize = 10) =>
    api.get<any>(`/agents/?page=${page}&page_size=${pageSize}`),
  get: (id: number) => api.get<ApiResponse<Agent>>(`/agents/${id}`),
  create: (data: AgentCreatePayload) =>
    api.post<ApiResponse<Agent>>("/agents/", data),
  update: (id: number, data: AgentUpdatePayload) =>
    api.put<ApiResponse<Agent>>(`/agents/${id}`, data),
  delete: (id: number) => api.delete(`/agents/${id}`),
  chat: (
    agentId: number,
    message: string,
    history?: ChatMessage[],
    conversationId?: number
  ) =>
    api.post<ApiResponse<{ response: string; conversation_id: number }>>(
      `/agents/${agentId}/chat`,
      {
        agent_id: agentId,
        message,
        history,
        // Only include the key when we have a value so the backend
        // auto-creates a fresh Conversation on first turn.
        ...(conversationId != null ? { conversation_id: conversationId } : {}),
      }
    ),
};
