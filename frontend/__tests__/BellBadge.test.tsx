import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { BellBadge } from "@/components/notifications/BellBadge";

vi.mock("@/store/notifications", () => ({
  useNotificationsStore: vi.fn(),
}));

import { useNotificationsStore } from "@/store/notifications";

const Wrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider>{children}</ConfigProvider>
);

describe("BellBadge", () => {
  it("shows no count when unread is 0", () => {
    (useNotificationsStore as any).mockImplementation((sel: any) => sel({
      unreadCount: 0, setDrawerOpen: vi.fn(),
    }));
    const { container } = render(<BellBadge />, { wrapper: Wrapper });
    expect(container.querySelector(".ant-badge-count")).toBeNull();
  });

  it("shows count when unread > 0", () => {
    (useNotificationsStore as any).mockImplementation((sel: any) => sel({
      unreadCount: 5, setDrawerOpen: vi.fn(),
    }));
    const { container } = render(<BellBadge />, { wrapper: Wrapper });
    expect(container.querySelector(".ant-badge-count")?.textContent).toBe("5");
  });
});
