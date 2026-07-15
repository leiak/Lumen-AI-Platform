import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ConfigProvider } from "antd";

vi.mock("@/store/notifications", () => ({
  useNotificationsStore: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import { useNotificationsStore } from "@/store/notifications";
import { NotificationDrawer } from "@/components/notifications/NotificationDrawer";

const Wrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider>{children}</ConfigProvider>
);

describe("NotificationDrawer", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renders notifications and shows unread count", () => {
    vi.mocked(useNotificationsStore).mockImplementation(((sel: any) => sel({
      drawerOpen: true, items: [
        { id: 1, type: "knowledge_parse_completed", title: "doc1 done", body: null,
          resource_type: "document", resource_id: 7, metadata: { kb_id: 3 },
          read_at: null, created_at: "2026-06-04T00:00:00" },
        { id: 2, type: "knowledge_parse_failed", title: "doc2 failed", body: "err",
          resource_type: "document", resource_id: 8, metadata: { kb_id: 3 },
          read_at: null, created_at: "2026-06-04T00:01:00" },
      ],
      unreadCount: 2, nextCursor: null,
      markRead: vi.fn(), markAllRead: vi.fn(), loadMore: vi.fn(),
      setDrawerOpen: vi.fn(),
    })));

    render(<NotificationDrawer />, { wrapper: Wrapper });
    expect(screen.getByText("doc1 done")).toBeTruthy();
    expect(screen.getByText("doc2 failed")).toBeTruthy();
  });

  it("calls markRead on item click", () => {
    const markRead = vi.fn();
    vi.mocked(useNotificationsStore).mockImplementation(((sel: any) => sel({
      drawerOpen: true, items: [
        { id: 1, type: "knowledge_parse_completed", title: "doc1 done", body: null,
          resource_type: "document", resource_id: 7, metadata: { kb_id: 3 },
          read_at: null, created_at: "2026-06-04T00:00:00" },
      ],
      unreadCount: 1, nextCursor: null,
      markRead, markAllRead: vi.fn(), loadMore: vi.fn(),
      setDrawerOpen: vi.fn(),
    })));

    render(<NotificationDrawer />, { wrapper: Wrapper });
    fireEvent.click(screen.getByText("doc1 done"));
    expect(markRead).toHaveBeenCalledWith(1);
  });
});
