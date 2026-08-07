"use client";

import { useCallback, useEffect, useState } from "react";
import { chatApi } from "@/services/chat";
import type { Conversation } from "@/types/chat";
import { useAppMessage } from "./useAppMessage";

/**
 * M30b-style: 对话列表 + 当前选中 + 创建 + 删除 + AgentKBBanner dismissed。
 *
 * 把 page.tsx 里的 conversations / currentConv / deletingId / creating /
 * bannerDismissedForConv + 4 个 fetch/handler 全收编。
 *
 * banner state 放这里是因为它的生命周期跟 conv 切换强绑定(切 conv / 切 agent /
 * 新建 conv 时都要重置),跟 conversations 走一处比拆成 useChatBanner + 跨 hook
 * 同步更稳。
 *
 * 调用方在切 agent 后调 `resetBannerDismissed()`(switch agent 也算"上下文变更")。
 */
export function useChatConversations() {
  const { message } = useAppMessage();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentConv, setCurrentConv] = useState<Conversation | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [bannerDismissedForConv, setBannerDismissedForConv] = useState<
    Set<number>
  >(() => new Set());

  const fetchConversations = useCallback(async () => {
    try {
      const res = await chatApi.listConversations();
      if (res.data.code === 200) {
        setConversations(res.data.data || []);
      }
    } catch (err) {
      message.error("加载对话列表失败");
    }
  }, [message]);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  const selectConv = useCallback(
    (conv: Conversation) => {
      setCurrentConv((prev) => {
        if (prev?.id !== conv.id) {
          // 切到另一个 conv → 重置 dismissed,让 banner 用新 conv 的 agent 重新出现
          setBannerDismissedForConv(new Set());
        }
        return conv;
      });
    },
    []
  );

  const resetBannerDismissed = useCallback(() => {
    setBannerDismissedForConv(new Set());
  }, []);

  const dismissBannerForConv = useCallback((convId: number) => {
    setBannerDismissedForConv((prev) => new Set([...prev, convId]));
  }, []);

  const createConversation = useCallback(
    async (agentId: number | null) => {
      setCreating(true);
      try {
        const res = await chatApi.createConversation({
          agent_id: agentId ?? undefined,
        });
        if (res.data.code === 200) {
          const newConv = res.data.data;
          setConversations((prev) => [newConv, ...prev]);
          setCurrentConv(newConv);
          setBannerDismissedForConv(new Set());
          return newConv;
        }
        message.error(res.data.message || "创建对话失败");
        return null;
      } catch (err) {
        // 详情通过 console.error 留给 devtools;UI toast 保持简短文案以兼容
        // page-agent-binding.test.tsx 的 getByText 精确匹配
        console.error("[Chat] createConversation failed:", err);
        message.error("创建对话失败");
        return null;
      } finally {
        setCreating(false);
      }
    },
    [message]
  );

  const deleteConversation = useCallback(
    async (id: number) => {
      setDeletingId(id);
      try {
        const res = await chatApi.deleteConversation(id);
        if (res.data.code === 200) {
          message.success("删除成功");
          await fetchConversations();
          // 删除当前选中 → 跳到最近一个(后端已过滤已软删,旧列表减一 == 新列表)
          setCurrentConv((prev) => {
            if (prev?.id !== id) return prev;
            const remaining = conversations.filter((c) => c.id !== id);
            if (remaining.length > 0) {
              setBannerDismissedForConv(new Set());
              return remaining[0];
            }
            return null;
          });
          return true;
        }
        message.error(res.data.message || "删除失败");
        return false;
      } catch (err) {
        // 详情通过 console.error 留给 devtools;UI toast 保持简短文案以兼容
        // page-delete.test.tsx 的 getByText 精确匹配
        console.error("[Chat] deleteConversation failed:", err);
        message.error("删除失败");
        return false;
      } finally {
        setDeletingId(null);
      }
    },
    [conversations, fetchConversations, message]
  );

  // 把 conversations + currentConv + agent_id 替换为目标 conv —— switchAgent
  // 飞行成功的 callback 用,避免重新拉列表。
  const applyUpdatedConv = useCallback((updated: Conversation) => {
    setConversations((prev) =>
      prev.map((c) => (c.id === updated.id ? updated : c))
    );
    setCurrentConv((prev) => (prev?.id === updated.id ? updated : prev));
  }, []);

  return {
    conversations,
    currentConv,
    setCurrentConv,
    deletingId,
    creating,
    bannerDismissedForConv,
    fetchConversations,
    selectConv,
    resetBannerDismissed,
    dismissBannerForConv,
    createConversation,
    deleteConversation,
    applyUpdatedConv,
  };
}