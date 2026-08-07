"use client";

import { useState, useEffect } from "react";
import { App, ConfigProvider, Button } from "antd";
import { useRouter, usePathname } from "next/navigation";
import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  UserOutlined,
  LogoutOutlined,
  BookOutlined,
  RobotOutlined,
  MessageOutlined,
  ShareAltOutlined,
  CloudServerOutlined,
  SettingOutlined,
  TeamOutlined,
  AppstoreOutlined,
  SafetyOutlined,
  ClockCircleOutlined,
  FileTextOutlined,
  ApiOutlined,
  PictureOutlined,
  SendOutlined,
  DatabaseOutlined,
  PlayCircleOutlined,
  DashboardOutlined,
  HistoryOutlined,
} from "@ant-design/icons";
import { ProLayout } from "@ant-design/pro-components";
import zhCN from "antd/locale/zh_CN";
import { BellBadge } from "@/components/notifications/BellBadge";
import { NotificationDrawer } from "@/components/notifications/NotificationDrawer";
import { useNotificationsStore } from "@/store/notifications";

const menuItems = [
  {
    path: "/dashboard",
    name: "首页",
    icon: <UserOutlined />,
  },
  {
    path: "/dashboard/knowledge",
    name: "知识库",
    icon: <BookOutlined />,
  },
  {
    path: "/dashboard/agent",
    name: "AI Agent",
    icon: <RobotOutlined />,
  },
  // M33 客户管理(CRM) — placed between AI Agent and 多代理团队(销售运营聚集)。
  // 用 2 个独立顶级菜单项(不嵌套)避开 ProLayout 的 parent/child path 重复警告。
  // child[0] = parent path 是 ProLayout 的硬限制 — 跟 wx-publisher 4 children
  // 全 unique 不同,customer 只有 2 项,standalone 更合适。
  {
    path: "/dashboard/customer",
    name: "客户列表",
    icon: <UserOutlined />,
  },
  {
    path: "/dashboard/customer/settings",
    name: "字段管理",
    icon: <AppstoreOutlined />,
  },
  {
    path: "/dashboard/agent/team",
    name: "多代理团队",
    icon: <TeamOutlined />,
  },
  {
    path: "/dashboard/chat",
    name: "Chat",
    icon: <MessageOutlined />,
  },
  // M32 公众号助手 — placed between Chat and Image Generation (运营工具聚集).
  {
    path: "/dashboard/wx-publisher",
    name: "公众号助手",
    icon: <SendOutlined />,
    children: [
      { path: "/dashboard/wx-publisher/drafts", name: "草稿管理" },
      { path: "/dashboard/wx-publisher/templates", name: "排版模板" },
      { path: "/dashboard/wx-publisher/materials", name: "素材库" },
      { path: "/dashboard/wx-publisher/accounts", name: "公众号账号" },
    ],
  },
  {
    path: "/dashboard/image-generation",
    name: "图片生成",
    icon: <PictureOutlined />,
  },
  // M36.1 视频合成 — placed between Image Generation and 智能问数 (media
  // generation tools 聚集,运营常用)。
  {
    path: "/dashboard/videos",
    name: "视频合成",
    icon: <PlayCircleOutlined />,
  },
  // M33 智能问数(Text2SQL) — placed between Image Generation and Memory
  // (数据 / 业务问数聚集,运营常用)。
  {
    path: "/dashboard/text2sql",
    name: "智能问数",
    icon: <DatabaseOutlined />,
  },
  // M37.1 + M37.3 — RAG 评测拆 parent + 2 children。
  // parent path = /dashboard/eval 即 M37.3 评测看板 (KPI + trend + run 列表) —
  // 借 layout.tsx:291-299 menuItemRender 强 router.push(item.path),点 parent
  // 直接去看板。子菜单展开后:
  //   - 评测数据集 → /dashboard/eval/datasets (M37.1 列表)
  //   - 评测运行   → /dashboard/eval/runs    (M37.3 新增列表)
  // 参照 wx-publisher (layout.tsx:60-69) parent + children 的现有形态。
  {
    path: "/dashboard/eval",
    name: "RAG 评测",
    icon: <DashboardOutlined />,
    children: [
      { path: "/dashboard/eval/datasets", name: "评测数据集" },
      { path: "/dashboard/eval/runs", name: "评测运行" },
    ],
  },
  {
    path: "/dashboard/memory",
    name: "记忆管理",
    icon: <ClockCircleOutlined />,
  },
  {
    path: "/dashboard/workflow",
    name: "工作流",
    icon: <ShareAltOutlined />,
  },
  {
    // M30 ship follow-up (2026-06-18): previously this lived as a
    // child of "工作流", but AntD ProLayout with children turns the
    // parent into a collapse toggle — clicking "工作流" expanded
    // the submenu but never navigated to the list page (the comment
    // claimed otherwise). Promote it to a sibling so the sidebar
    // has two independent entries: 工作流 → list, 模板中心 →
    // templates gallery. The two pages now link to each other
    // directly (button in the page top bar) so the user never has
    // to come back through the sidebar to switch.
    path: "/dashboard/workflow/templates",
    name: "模板中心",
    icon: <AppstoreOutlined />,
  },
  {
    path: "/dashboard/mcp",
    name: "MCP",
    icon: <CloudServerOutlined />,
  },
  {
    path: "/dashboard/electron",
    name: "桌面端",
    icon: <AppstoreOutlined />,
  },
  {
    path: "/dashboard/skills/installed",
    name: "我的技能",
    icon: <AppstoreOutlined />,
  },
  {
    path: "/dashboard/skills/market",
    name: "技能市场",
    icon: <AppstoreOutlined />,
  },
  {
    path: "/dashboard/marketplace",
    name: "工作流市场",
    icon: <AppstoreOutlined />,
  },
  {
    path: "/dashboard/system",
    name: "系统设置",
    icon: <SettingOutlined />,
    children: [
      {
        path: "/dashboard/system/users",
        name: "用户管理",
        icon: <TeamOutlined />,
      },
      {
        path: "/dashboard/system/roles",
        name: "角色管理",
        icon: <SafetyOutlined />,
      },
      {
        path: "/dashboard/system/models",
        name: "模型配置",
        icon: <AppstoreOutlined />,
      },
      {
        path: "/dashboard/system/settings",
        name: "系统设置",
        icon: <SettingOutlined />,
      },
      {
        path: "/dashboard/external-apps",
        name: "外部应用授权",
        icon: <ApiOutlined />,
      },
    ],
  },
  {
    path: "/dashboard/logs",
    name: "日志审计",
    icon: <FileTextOutlined />,
  },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [currentUser, setCurrentUser] = useState<{ username: string; tenant_id: number } | null>(null);
  const router = useRouter();
  const pathname = usePathname();
  // 通知抽屉打开时,右上角 fixed 顶栏要降 z-index,否则 z=9999 盖在 AntD Drawer (z=1000) 之上
  const drawerOpen = useNotificationsStore((s) => s.drawerOpen);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Fetch current user info from /auth/me
  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) return;
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.json())
      .then((body) => {
        if (body.code === 200 && body.data) {
          setCurrentUser({ username: body.data.username, tenant_id: body.data.tenant_id });
        }
      })
      .catch(() => {});
  }, []);

  // Fire-and-forget: init() mutates the store; subscribers re-render.
  // The store's _inited guard makes this safe under React StrictMode
  // double-mount. Token rotation is handled by the auth 401 interceptor
  // (services/auth.ts) which triggers a full reload.
  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (token) useNotificationsStore.getState().init(token);
  }, []);

  const handleLogout = () => {
    if (window.confirm("确定要退出登录吗？")) {
      localStorage.removeItem("access_token");
      localStorage.removeItem("user");
      useNotificationsStore.getState().reset();
      router.push("/login");
    }
  };

  return (
    <ConfigProvider locale={zhCN}>
      <App>
        {/* 退出按钮 - 固定在右上角。drawer 打开时 zIndex 降到 900,让出给 AntD Drawer (z=1000) */}
        <div
          style={{
            position: "fixed",
            top: 16,
            right: 24,
            zIndex: drawerOpen ? 900 : 9999,
            display: "flex",
            alignItems: "center",
            gap: 12,
            transition: "z-index 0s",
          }}
        >
          <span style={{ color: "#000", fontSize: 14 }}>{currentUser?.username ?? "Admin"}</span>
          <Button
            type="text"
            icon={<LogoutOutlined />}
            onClick={handleLogout}
            style={{ color: "#000" }}
          >
            退出
          </Button>
          <BellBadge />
        </div>
        <NotificationDrawer />
        {mounted ? (
        <ProLayout
          title="Lumen AI Platform"
          layout="mix"
          contentWidth="Fluid"
          fixedHeader
          fixSiderbar
          collapsed={collapsed}
          onCollapse={setCollapsed}
          menuDataRender={() => menuItems}
          location={{ pathname }}
          menuItemRender={(item, dom) => (
            <div
              onClick={() => {
                router.push(item.path || "/dashboard");
              }}
            >
              {dom}
            </div>
          )}
          avatarProps={{
            title: currentUser?.username ?? "User",
            render: () => null,
          }}
        >
          {children}
        </ProLayout>
        ) : (
          <div style={{ minHeight: "100vh" }}>{children}</div>
        )}
      </App>
    </ConfigProvider>
  );
}
