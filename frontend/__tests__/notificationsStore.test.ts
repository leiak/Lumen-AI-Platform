import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/services/notifications", () => ({
  notificationsApi: {
    list: vi.fn(),
    unreadCount: vi.fn(),
    markRead: vi.fn(),
    markAllRead: vi.fn(),
  },
  Notification: {},
}));

vi.mock("@/services/realtime", () => ({
  realtime: {
    connect: vi.fn(),
    disconnect: vi.fn(),
    onMessage: vi.fn(() => () => {}),
    onStatusChange: vi.fn(() => () => {}),
  },
}));

// Silences the lazy `import("antd").then(notification.open)` side effect
// triggered by addIncoming. AntD's notification uses rc-notification +
// rc-motion which can hang in jsdom when no DOM container exists; this
// mock keeps the test deterministic without touching the store impl.
vi.mock("antd", () => ({
  notification: { open: vi.fn() },
}));

import { notificationsApi } from "@/services/notifications";
import { realtime } from "@/services/realtime";

describe("notifications store", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
  });

  it("init() fetches initial list and connects ws", async () => {
    (notificationsApi.list as any).mockResolvedValue({
      items: [
        { id: 1, type: "knowledge_parse_completed", title: "t", body: null,
          resource_type: "document", resource_id: 7, metadata: { kb_id: 3 },
          read_at: null, created_at: "2026-06-04T00:00:00" },
      ],
      next_cursor: null,
      unread_count: 1,
    });
    const { useNotificationsStore } = await import("@/store/notifications");
    await useNotificationsStore.getState().init("tok");
    const s = useNotificationsStore.getState();
    expect(s.items).toHaveLength(1);
    expect(s.unreadCount).toBe(1);
    expect(realtime.connect).toHaveBeenCalledWith("tok");
  });

  it("addIncoming prepends and increments unread", async () => {
    (notificationsApi.list as any).mockResolvedValue({ items: [], next_cursor: null, unread_count: 0 });
    const { useNotificationsStore } = await import("@/store/notifications");
    await useNotificationsStore.getState().init("tok");
    useNotificationsStore.getState().addIncoming({
      id: 99, type: "knowledge_parse_completed", title: "new", body: null,
      resource_type: "document", resource_id: 1, metadata: { kb_id: 1 },
      read_at: null, created_at: "2026-06-04T01:00:00",
    });
    const s = useNotificationsStore.getState();
    expect(s.items[0].id).toBe(99);
    expect(s.unreadCount).toBe(1);
  });

  it("addIncoming is idempotent on duplicate id", async () => {
    (notificationsApi.list as any).mockResolvedValue({ items: [], next_cursor: null, unread_count: 0 });
    const { useNotificationsStore } = await import("@/store/notifications");
    await useNotificationsStore.getState().init("tok");
    const n = {
      id: 50, type: "x", title: "t", body: null,
      resource_type: null, resource_id: null, metadata: null,
      read_at: null, created_at: "2026-06-04T01:00:00",
    };
    useNotificationsStore.getState().addIncoming(n);
    useNotificationsStore.getState().addIncoming(n);
    expect(useNotificationsStore.getState().items).toHaveLength(1);
  });

  it("markRead removes unread from count and clears timestamp", async () => {
    (notificationsApi.list as any).mockResolvedValue({ items: [], next_cursor: null, unread_count: 0 });
    (notificationsApi.markRead as any).mockResolvedValue({ id: 1, read_at: "2026-06-04T01:00:00" });
    const { useNotificationsStore } = await import("@/store/notifications");
    await useNotificationsStore.getState().init("tok");
    useNotificationsStore.getState().addIncoming({
      id: 1, type: "x", title: "t", body: null,
      resource_type: null, resource_id: null, metadata: null,
      read_at: null, created_at: "2026-06-04T01:00:00",
    });
    await useNotificationsStore.getState().markRead(1);
    const s = useNotificationsStore.getState();
    expect(s.unreadCount).toBe(0);
    expect(s.items[0].read_at).not.toBeNull();
  });
});
