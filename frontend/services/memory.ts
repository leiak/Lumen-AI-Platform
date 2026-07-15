import api from "./auth";
import type { ApiResponse } from "@/types/api";

export interface MemoryMessage {
  role: "user" | "assistant" | "system";
  content: string;
  metadata?: Record<string, unknown>;
  // M15: source conversation; undefined for legacy rows written before
  // the column existed, or for any future caller that doesn't know
  // the source. The UI uses it to dim/filter current-conv rows in
  // /dashboard/memory's global context panel.
  conversation_id?: number | null;
}

export const memoryApi = {
  getHistory: (conversationId: number, limit = 50) =>
    api.get<ApiResponse<MemoryMessage[]>>(`/memory/conversations/${conversationId}?limit=${limit}`),
  searchMemory: (conversationId: number, query: string) =>
    api.get<ApiResponse<MemoryMessage[]>>(`/memory/conversations/${conversationId}/search?query=${encodeURIComponent(query)}`),
  clearMemory: (conversationId: number) =>
    api.delete<ApiResponse<void>>(`/memory/conversations/${conversationId}`),
  getGlobalContext: (query?: string) =>
    api.get<ApiResponse<MemoryMessage[]>>(`/memory/global${query ? `?query=${encodeURIComponent(query)}` : ""}`),
};
