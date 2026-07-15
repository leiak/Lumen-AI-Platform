"use client";
import { Drawer, List, Button, Empty, Tag, theme } from "antd";
import { useRouter } from "next/navigation";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import "dayjs/locale/zh-cn";
import { useNotificationsStore } from "@/store/notifications";
import type { Notification } from "@/services/notifications";
import { useShallow } from "zustand/react/shallow";

dayjs.extend(relativeTime);
dayjs.locale("zh-cn");

export function NotificationDrawer() {
  const router = useRouter();
  const { token } = theme.useToken();
  const { drawerOpen, items, unreadCount, nextCursor,
          markRead, markAllRead, loadMore, setDrawerOpen } =
    useNotificationsStore(useShallow((s) => ({
      drawerOpen: s.drawerOpen,
      items: s.items,
      unreadCount: s.unreadCount,
      nextCursor: s.nextCursor,
      markRead: s.markRead,
      markAllRead: s.markAllRead,
      loadMore: s.loadMore,
      setDrawerOpen: s.setDrawerOpen,
    })));

  const handleClick = (n: Notification) => {
    markRead(n.id);
    if (n.resource_type === "document" && n.metadata?.kb_id && n.resource_id) {
      setDrawerOpen(false);
      router.push(`/dashboard/knowledge?kb=${n.metadata.kb_id}&doc=${n.resource_id}`);
    }
  };

  return (
    <Drawer
      title="通知"
      placement="right"
      width={420}
      open={drawerOpen}
      onClose={() => setDrawerOpen(false)}
      extra={
        unreadCount > 0 ? (
          <Button type="link" onClick={markAllRead}>全部已读</Button>
        ) : null
      }
    >
      {items.length === 0 ? (
        <Empty description="暂无通知" />
      ) : (
        <List
          dataSource={items}
          renderItem={(n) => (
            <List.Item
              onClick={() => handleClick(n)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  handleClick(n);
                }
              }}
              role="button"
              tabIndex={0}
              style={{ cursor: "pointer" }}
            >
              <List.Item.Meta
                title={
                  <span>
                    {n.read_at ? null : (
                      <Tag color="blue" style={{ marginRight: 8 }}>新</Tag>
                    )}
                    {n.title}
                  </span>
                }
                description={
                  <>
                    {n.body && <div style={{ color: token.colorTextSecondary }}>{n.body}</div>}
                    <div style={{ color: token.colorTextTertiary, fontSize: token.fontSizeSM }}>
                      {dayjs(n.created_at).fromNow()}
                    </div>
                  </>
                }
              />
            </List.Item>
          )}
        />
      )}
      {nextCursor && (
        <div style={{ textAlign: "center", marginTop: 12 }}>
          <Button onClick={loadMore}>加载更多</Button>
        </div>
      )}
    </Drawer>
  );
}
