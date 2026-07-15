import api, { ApiResponse } from "./auth";
import type { Message, Conversation, AttachmentRef } from "@/types/chat";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:11335/api/v1";

export interface SkillRecommendation {
  skill_id: number;
  marketplace_skill_id: number;
  name: string;
  description?: string;
  reason: string;
  confidence: number;
  match_type: "keyword" | "llm";
}

export interface UploadResult {
  file_id: string;
  name: string;
  size: number;
  mime_type: string;
  content_text: string;
}

export const chatApi = {
  listConversations: () =>
    api.get<ApiResponse<Conversation[]>>(`/chat/conversations`),

  createConversation: (data: { title?: string; agent_id?: number }) =>
    api.post<ApiResponse<Conversation>>("/chat/conversations", data),

  getMessages: (conversationId: number) =>
    api.get<ApiResponse<Message[]>>(`/chat/conversations/${conversationId}/messages`),

  deleteConversation: (id: number) =>
    api.delete<ApiResponse<null>>(`/chat/conversations/${id}`),

  updateConversation: (id: number, data: { agent_id?: number | null }) =>
    api.patch<ApiResponse<Conversation>>(`/chat/conversations/${id}`, data),

  uploadAttachment: async (file: File, token: string): Promise<UploadResult> => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${API_BASE}/chat/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: fd,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`upload failed: ${res.status} ${text}`);
    }
    const json = await res.json();
    if (json.code !== 200 || !json.data) {
      throw new Error(`upload returned bad payload: ${JSON.stringify(json)}`);
    }
    return json.data as UploadResult;
  },

  streamChat: async (
    data: {
      message: string;
      conversation_id?: number;
      agent_id?: number;
      enable_thinking?: boolean;
      enable_web_search?: boolean;
      attachments?: AttachmentRef[];
      skill_ids?: number[];   // NEW — list of Skill.id; backend silently drops invalid ones
    },
    token: string
  ) => {
    const response = await fetch(`${API_BASE}/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`,
      },
      body: JSON.stringify(data),
    });
    return response.body;
  },

  recommendSkills: (message: string, token: string): Promise<SkillRecommendation[]> => {
    return fetch(`${API_BASE}/chat/recommend-skills`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`,
      },
      body: JSON.stringify({ message }),
    }).then((res) => {
      if (!res.ok) throw new Error(`recommend-skills failed: ${res.status}`);
      return res.json();
    }).then((json) => {
      if (json.code !== 200 || !Array.isArray(json.data)) {
        return [] as SkillRecommendation[];
      }
      return json.data as SkillRecommendation[];
    });
  },
};
