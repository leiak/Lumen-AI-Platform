"use client";

import { useCallback, useEffect, useState } from "react";
import { skillsApi, type InstalledSkill } from "@/services/skills";
import { useAppMessage, extractErrorDetail } from "./useAppMessage";

/**
 * M30b-style: 已装技能列表 + 技能选择弹窗 state。
 *
 * - `installedSkills`: 弹窗打开时拉一次(modal on-demand fetch)。
 * - `pickerOpen` / `draftSkillIds`: 弹窗 state。
 * - `commit(max=5)` / `cancel()`: 弹窗 OK/取消,把 draftSkillIds 合并到上层
 *   通过 `onCommit(skillIds)` 传出去的 callback 上层应用。
 *
 * 调用方通过 `setOnCommit(fn)` 注册提交回调 —— 因为这个 hook 不知道上层要把
 * skillIds 灌到哪里(toggles.skillIds);用 ref 注册避免 commit 闭包过期。
 */
export function useChatSkills() {
  const { message } = useAppMessage();
  const [installedSkills, setInstalledSkills] = useState<
    { value: number; label: string; category: string }[]
  >([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [draftSkillIds, setDraftSkillIds] = useState<number[]>([]);

  useEffect(() => {
    if (!pickerOpen) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await skillsApi.listInstalled(1, 50);
        if (cancelled) return;
        if (res.data.code === 200) {
          // listInstalled returns a PaginatedResponse — data 是数组本身,不是
          // 嵌套对象 (2026-08-07 之前有 stale bug:读 res.data.data?.data)
          const list = Array.isArray(res.data.data) ? res.data.data : [];
          const items = list.map((s: InstalledSkill) => ({
            value: s.skill_id,
            label: s.name,
            category: s.category,
          }));
          setInstalledSkills(items);
        } else {
          message.error(res.data.message || "加载已装技能失败");
        }
      } catch (err) {
        if (cancelled) return;
        message.error(`加载已装技能失败:${extractErrorDetail(err, "")}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pickerOpen, message]);

  const openPicker = useCallback((currentSkillIds: number[]) => {
    setDraftSkillIds(currentSkillIds);
    setPickerOpen(true);
  }, []);

  const closePicker = useCallback(() => {
    setPickerOpen(false);
  }, []);

  const setDraft = useCallback((ids: number[]) => {
    setDraftSkillIds(ids.slice(0, 5));
  }, []);

  return {
    installedSkills,
    pickerOpen,
    draftSkillIds,
    openPicker,
    closePicker,
    setDraft,
  };
}