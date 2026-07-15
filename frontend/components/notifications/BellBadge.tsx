"use client";
import { Badge, Button } from "antd";
import { BellOutlined } from "@ant-design/icons";
import { useShallow } from "zustand/react/shallow";
import { useNotificationsStore } from "@/store/notifications";

export function BellBadge() {
  const { unreadCount, setDrawerOpen } = useNotificationsStore(
    useShallow((s) => ({ unreadCount: s.unreadCount, setDrawerOpen: s.setDrawerOpen }))
  );
  return (
    <Badge count={unreadCount} size="small" offset={[-4, 4]}>
      <Button
        type="text"
        shape="circle"
        icon={<BellOutlined />}
        onClick={() => setDrawerOpen(true)}
        aria-label="通知"
      />
    </Badge>
  );
}
