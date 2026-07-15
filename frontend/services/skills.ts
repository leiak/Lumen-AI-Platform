import api from "./auth";
import type { ApiResponse } from "@/types/api";

export interface MarketplaceSkill {
  id: number;
  name: string;
  category: string;
  description: string;
  downloads: number;
  rating: number;
  content?: string;  // 技能实际 prompt,list/installed/detail 三处同步带(M15 2026-06-09)
  is_installed?: boolean;  // 当前用户是否已装(M15 2026-06-09,action 列 disabled 用)
  version?: string;  // 详情 drawer 显示用(M15 2026-06-09)
  provider?: string;  // 详情 drawer 显示用(M15 2026-06-09)
  is_verified?: boolean;  // 详情 drawer 显示用(M15 2026-06-09)
  // M16 (2026-06-10): type + type_config
  type?: string;  // "prompt" | "script" | "http" | (M17) | (M18)
  type_config?: Record<string, any>;
}

export interface InstalledSkill {
  id: number;                    // marketplace_skill_id (== SkillMarketplace.id)
  skill_id: number;              // Skill.id — what the frontend sends back as skill_ids
  name: string;
  category: string;
  description?: string;
  version: string;
  provider?: string;
  installed_at?: string;
  is_installed?: boolean;
  rating?: string;
  downloads?: number;
}

export const skillsApi = {
  listMarketplace: (category?: string) =>
    api.get<any>(`/skills/market/${category ? `?category=${category}` : ""}`),
  installSkill: (skillId: number) =>
    api.post<any>(`/skills/market/${skillId}/install`),

  // M15 (2026-06-09) 详情查看:返回单条 skill 的完整元数据 + content
  getMarketplaceSkill: (skillId: number) =>
    api.get<any>(`/skills/market/${skillId}`),

  listInstalled: (page = 1, pageSize = 50) =>
    api.get<any>(`/skills/market/installed?page=${page}&page_size=${pageSize}`),

  uninstallSkill: (marketplaceSkillId: number) =>
    api.post<any>(`/skills/market/${marketplaceSkillId}/uninstall`),

  // M20 (2026-06-11) batch uninstall
  batchUninstall: (ids: number[]) =>
    api.post<any>("/skills/market/batch-uninstall", { ids }),

  getCategories: () =>
    api.get<any>(`/skills/market/categories`),
};

// M17 (2026-06-10) admin skills API
export const skillAdminApi = {
  testRun: (skillId: number, inputArgs: Record<string, any>) =>
    api.post<any>(`/admin/skills/${skillId}/test-run`, {
      input_args: inputArgs,
    }),
  list: (type?: string) =>
    api.get<any>(`/admin/skills/${type ? `?type=${type}` : ""}`),
};