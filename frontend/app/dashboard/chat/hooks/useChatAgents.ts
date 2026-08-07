"use client";

import { useCallback, useEffect, useState } from "react";
import { agentApi } from "@/services/agent";
import { chatApi } from "@/services/chat";
import type { Agent } from "@/types/api";
import type { Conversation } from "@/types/chat";
import { useAppMessage, extractErrorDetail } from "./useAppMessage";

/**
 * M30b-style: Agent 列表 + 当前 conv 切换 Agent + 新建对话时选 Agent。
 *
 * - `agents` / `agentPickerLoading`: 全 tenant 可见的 active Agent 列表。
 * - `updatingAgentId`: 哪个 conv 正在 PATCH(防 2026-06-08 评审 Important #1
 *   的竞态 —— 切 agent 飞行期间用户切 conv 时,旧 PATCH 回来会覆盖新选中的 conv)。
 * - `createAgentId` / `createOpen`: 新建对话 modal 的 agent 选择。
 *
 * 返回的 `switchAgentForConv` 接收一个 explicit convId,**不**从 currentConv
 * 闭包取 —— 保证 PATCH 飞行期间切换 conv 后旧响应不会污染新选中的 conv。
 */
export function useChatAgents() {
  const { message } = useAppMessage();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentPickerLoading, setAgentPickerLoading] = useState(false);
  const [updatingAgentId, setUpdatingAgentId] = useState<number | null>(null);
  const [createAgentId, setCreateAgentId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const fetchAgents = useCallback(async () => {
    setAgentPickerLoading(true);
    try {
      const res = await agentApi.list(1, 100);
      if (res.data.code === 200) {
        const list = Array.isArray(res.data.data) ? res.data.data : [];
        // 后端不过滤 is_active,前端兜底
        setAgents(list.filter((a: Agent) => a.is_active));
      }
    } catch (err) {
      message.error("加载 Agent 列表失败");
    } finally {
      setAgentPickerLoading(false);
    }
  }, [message]);

  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  const openCreateModal = useCallback(() => {
    setCreateAgentId(null);
    setCreateOpen(true);
  }, []);

  const closeCreateModal = useCallback(() => {
    setCreateOpen(false);
  }, []);

  // 切 agent:由调用方传 currentConv 进来,这里 snapshot convId 后用 functional
  // update 避免 closure-capture 旧 conv —— 见 2026-06-08 评审 Important #1。
  const switchAgentForConv = useCallback(
    async (convId: number, currentConv: Conversation | null, newAgentId: number | null) => {
      if (!currentConv) return;
      setUpdatingAgentId(convId);
      try {
        const res = await chatApi.updateConversation(convId, {
          agent_id: newAgentId,
        });
        if (res.data.code === 200) {
          const updated = res.data.data;
          if (!updated) {
            message.error("服务器返回为空");
            return;
          }
          const agentName = newAgentId
            ? (agents.find((a) => a.id === newAgentId)?.name || "该 Agent")
            : "默认模型";
          message.success(`已切换到 ${agentName},后续回复风格会变`);
          return updated;
        }
        message.error(res.data.message || "切换失败");
        return null;
      } catch (err) {
        message.error(`切换失败:${extractErrorDetail(err, "")}`);
        return null;
      } finally {
        setUpdatingAgentId(null);
      }
    },
    [agents, message]
  );

  return {
    agents,
    agentPickerLoading,
    updatingAgentId,
    createAgentId,
    setCreateAgentId,
    createOpen,
    openCreateModal,
    closeCreateModal,
    switchAgentForConv,
    refresh: fetchAgents,
  };
}