import api from "./auth";

export interface Notification {
  id: number;
  type: string;
  title: string;
  body: string | null;
  resource_type: string | null;
  resource_id: number | null;
  metadata: Record<string, any> | null;
  read_at: string | null;
  created_at: string;
}

export interface NotificationListResponse {
  items: Notification[];
  next_cursor: number | null;
  unread_count: number;
}

export const notificationsApi = {
  list: async (params: { unread_only?: boolean; limit?: number; cursor?: number } = {}) => {
    // Path is relative to the axios baseURL in services/auth.ts
    // (which already includes `/api/v1`). An absolute `/api/v1/...`
    // here would concat to `/api/v1/api/v1/notifications` and 404.
    const r = await api.get("/notifications", { params });
    return r.data.data as NotificationListResponse;
  },
  unreadCount: async () => {
    const r = await api.get("/notifications/unread-count");
    return r.data.data as { count: number };
  },
  markRead: async (id: number) => {
    const r = await api.post(`/notifications/${id}/read`);
    return r.data.data;
  },
  markAllRead: async () => {
    const r = await api.post("/notifications/read-all");
    return r.data.data as { affected: number };
  },
};
