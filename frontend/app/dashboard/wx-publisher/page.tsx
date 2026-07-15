// frontend/app/dashboard/wx-publisher/page.tsx
// P0-1 (2026-06-20) — 公众号助手父路径 redirect.
// sidebar 把「公众号助手」写成有 children 的父菜单 (layout.tsx:60-69),
// 但 wx-publisher/ 下只有 4 个子目录 (drafts/templates/materials/accounts),
// 没有 page.tsx → 直接访问 /dashboard/wx-publisher 返 404.
// 修法: server component 立即重定向到 drafts (默认子页,运营最高频).

import { redirect } from "next/navigation";

export default function WxPublisherIndex() {
  redirect("/dashboard/wx-publisher/drafts");
}
