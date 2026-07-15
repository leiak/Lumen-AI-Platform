// 共享 KB list 工具:KBSelector 和 MultiKBSelector 都用。
// 抽取 list 加载和 optionRender 的最小公共逻辑,避免两个组件各写一份。
import { knowledgeApi } from "@/services/knowledge";
import type { KnowledgeBase } from "@/types/api";
import type { ReactNode } from "react";

export type KBOption = {
  id: number;
  name: string;
  status: string;
};

/**
 * 拉一页 KB(最多 100 条),转成精简的 {id, name, status} 列表。
 * 后端返回的是 PaginatedResponse<KnowledgeBase>,data 字段直接是数组
 * (不是 { items: [...] } —— 见 frontend/types/api.ts 的 PaginatedResponse)。
 * code != 200 时返回空数组,让调用方自己处理 error UI。
 */
export async function fetchAllKBOptions(): Promise<KBOption[]> {
  const res = await knowledgeApi.list(1, 100);
  if (res.data.code !== 200) return [];
  return (res.data.data as KnowledgeBase[]).map((kb) => ({
    id: kb.id,
    name: kb.name,
    status: kb.status,
  }));
}

/**
 * Select option 的统一渲染:名称 + 非 active 时附 status tag。
 * KBSelector 当前用的是 Select 默认 label(option.label),
 * 这个函数先准备好,等 T15 的 MultiKBSelector 直接用。
 */
export function renderKBOption(option: KBOption): ReactNode {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span>{option.name}</span>
      {option.status !== "active" && (
        <span style={{ color: "#999", fontSize: 12 }}>({option.status})</span>
      )}
    </div>
  );
}
