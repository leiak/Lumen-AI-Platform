import { create } from "zustand";
import { Notification, notificationsApi } from "@/services/notifications";
import { realtime } from "@/services/realtime";

interface State {
  items: Notification[];
  unreadCount: number;
  drawerOpen: boolean;
  nextCursor: number | null;
  /** ref-guard so React StrictMode doesn't double-init. */
  _inited: boolean;
  /** set to true on the first 4401 so we don't keep hammering auth. */
  _authFailed: boolean;

  init: (token: string) => Promise<void>;
  addIncoming: (n: Notification) => void;
  markRead: (id: number) => Promise<void>;
  markAllRead: () => Promise<void>;
  loadMore: () => Promise<void>;
  refetchUnread: () => Promise<void>;
  setDrawerOpen: (open: boolean) => void;
  reset: () => void;
}

export const useNotificationsStore = create<State>((set, get) => ({
  items: [],
  unreadCount: 0,
  drawerOpen: false,
  nextCursor: null,
  _inited: false,
  _authFailed: false,

  init: async (token: string) => {
    if (get()._inited) return;
    set({ _inited: true, _authFailed: false });
    try {
      const r = await notificationsApi.list({ unread_only: true, limit: 20 });
      set({ items: r.items, unreadCount: r.unread_count, nextCursor: r.next_cursor });
    } catch { /* auth likely failed; ws will surface 4401 */ }
    realtime.connect(token);
    realtime.onMessage(({ event, payload }) => {
      if (event === "notification_created") {
        get().addIncoming(payload as Notification);
      }
    });
    realtime.onStatusChange((status) => {
      if (status === "open") {
        // We may have just reconnected; backfill any missed events.
        get().refetchUnread();
      }
    });
  },

  addIncoming: (n) => {
    const s = get();
    if (s.items.some(x => x.id === n.id)) return;
    set({
      items: [n, ...s.items],
      unreadCount: s.unreadCount + 1,
    });
    // AntD top-right toast. The success/failure UX is owned by the
    // Drawer, not the store; the store just dispatches a generic
    // notification. We import lazily to keep the store SSR-safe.
    import("antd").then(({ notification }) => {
      notification.open({
        message: n.title,
        description: n.body ?? undefined,
        placement: "topRight",
        duration: n.type === "knowledge_parse_failed" ? 0 : 6,
      });
    });
  },

  markRead: async (id) => {
    // Capture wasUnread BEFORE set(): in zustand v5, get() inside a set
    // callback returns the PRE-update state, so checking read_at there would
    // always see the old (still-unread) value and skip the decrement.
    const wasUnread = !get().items.find((x) => x.id === id)?.read_at;
    try { await notificationsApi.markRead(id); } catch { /* ignore */ }
    set((s) => ({
      items: s.items.map((x) => x.id === id ? { ...x, read_at: new Date().toISOString() } : x),
      unreadCount: wasUnread ? Math.max(0, s.unreadCount - 1) : s.unreadCount,
    }));
  },

  markAllRead: async () => {
    let affected = 0;
    try {
      const r = await notificationsApi.markAllRead();
      affected = r.affected;
    } catch { /* ignore */ }
    set((s) => ({
      items: s.items.map((x) => x.read_at ? x : { ...x, read_at: new Date().toISOString() }),
      unreadCount: Math.max(0, s.unreadCount - affected),
    }));
  },

  loadMore: async () => {
    const { nextCursor } = get();
    if (!nextCursor) return;
    const r = await notificationsApi.list({ limit: 20, cursor: nextCursor });
    set((s) => ({
      items: [...s.items, ...r.items],
      nextCursor: r.next_cursor,
    }));
  },

  refetchUnread: async () => {
    try {
      const r = await notificationsApi.list({ unread_only: true, limit: 20 });
      // Merge: keep any items the WS already gave us.
      const byId = new Map<number, Notification>();
      for (const n of r.items) byId.set(n.id, n);
      for (const n of get().items) if (!byId.has(n.id)) byId.set(n.id, n);
      const merged = Array.from(byId.values()).sort((a, b) => b.id - a.id);
      set({ items: merged, unreadCount: r.unread_count });
    } catch { /* ignore */ }
  },

  setDrawerOpen: (open) => set({ drawerOpen: open }),

  reset: () => {
    realtime.disconnect();
    set({ items: [], unreadCount: 0, drawerOpen: false, nextCursor: null, _inited: false, _authFailed: false });
  },
}));
