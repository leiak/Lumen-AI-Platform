"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { chatApi, type SkillRecommendation } from "@/services/chat";
import type { AttachmentRef, Conversation, Message } from "@/types/chat";
import type { FeatureTogglesState as FeatureToggles } from "@/components/chat/FeatureToggles";
import { mergeDoneMetadata, type DoneEvent } from "@/lib/chat-sse-utils";
import { useAppMessage, extractErrorDetail } from "./useAppMessage";

/**
 * M30b-style: 消息列表 + 流式发送 + 技能推荐弹窗 + 重置 hooks。
 *
 * 把 page.tsx 里最复杂的部分抽出来:
 * - `fetchMessages(convId)` — 切换 conv 时调用
 * - `handleSend(...)` — 输入框 + 附件 → 触发技能推荐或直接发送
 * - `doSend(...)` — 真正的流式 SSE 解析
 * - `clearMessagesForNewConv()` — 新建 conv 时清空
 * - recommend modal 的所有 state
 *
 * 调用方传入:
 * - `currentConv` — 用来拿 convId 给 send 用
 * - `toggles` — feature toggles (thinking / web search / skill ids)
 * - `attachments` — 当前对话的附件列表
 *
 * 调用方监听:
 * - `streaming` — UI 上 disable input + send button
 * - `recommendModalOpen` / `recommendedSkills` / `selectedRecommendIds` —
 *   控制技能推荐 modal
 *
 * 暴露 `pendingMessage` / `pendingAttachments` 让 recommend modal 取消 / 确认
 * 时拿到弹窗期间的快照。
 */
export function useChatMessages(currentConv: Conversation | null) {
  const { message } = useAppMessage();
  const DEBUG = process.env.NODE_ENV === "development";
  const debugLog = useCallback(
    (...args: unknown[]) => {
      if (DEBUG) console.log(...args);
    },
    [DEBUG]
  );

  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [recommendModalOpen, setRecommendModalOpen] = useState(false);
  const [recommendedSkills, setRecommendedSkills] = useState<SkillRecommendation[]>([]);
  const [selectedRecommendIds, setSelectedRecommendIds] = useState<number[]>([]);
  const [pendingMessage, setPendingMessage] = useState("");
  const [pendingAttachments, setPendingAttachments] = useState<AttachmentRef[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  // 自动滚到底部 —— chat 通用模式
  const scrollToBottom = useCallback(() => {
    setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, 100);
  }, []);

  // 切换 conv → 重新拉消息
  useEffect(() => {
    if (!currentConv) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await chatApi.getMessages(currentConv.id);
        if (cancelled) return;
        if (res.data.code === 200) {
          setMessages(res.data.data || []);
          scrollToBottom();
        }
      } catch (err) {
        if (cancelled) return;
        message.error("加载消息失败");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentConv, message, scrollToBottom]);

  // 实际 SSE 流式发送
  const doSend = useCallback(
    async (
      userMsg: string,
      finalSkillIds: number[],
      msgAttachments: AttachmentRef[],
      toggles: FeatureToggles
    ) => {
      if (!userMsg || streaming || !currentConv) return;

      const convId = currentConv.id;
      setStreaming(true);

      // Optimistic append
      const tempUserMsg: Message = {
        id: Date.now(),
        conversation_id: convId,
        role: "user",
        content: userMsg,
        created_at: new Date().toISOString(),
        metadata:
          msgAttachments.length > 0
            ? {
                attachments: msgAttachments.map((a) => ({
                  name: a.name,
                  size: a.size,
                  mime_type: a.mime_type,
                })),
              }
            : undefined,
      };
      setMessages((prev) => [...prev, tempUserMsg]);
      scrollToBottom();

      try {
        const token = localStorage.getItem("access_token") || "";
        debugLog("[Chat] Sending request:", {
          message: userMsg,
          conversation_id: convId,
        });
        const response = await chatApi.streamChat(
          {
            message: userMsg,
            conversation_id: convId,
            agent_id: currentConv.agent_id,
            enable_thinking: toggles.enableThinking,
            enable_web_search: toggles.enableWebSearch,
            attachments: msgAttachments.length > 0 ? msgAttachments : undefined,
            skill_ids: finalSkillIds.length > 0 ? finalSkillIds : undefined,
          },
          token
        );
        debugLog("[Chat] Response received:", response);
        if (!response) {
          message.error("发送消息失败:服务器未返回响应");
          return;
        }

        const reader = response.getReader();
        const decoder = new TextDecoder();
        let assistantMsg = "";
        let assistantMsgAdded = false;
        let streamDone = false;

        while (!streamDone) {
          const { done, value } = await reader.read();
          if (done) {
            streamDone = true;
            break;
          }
          const chunk = decoder.decode(value);
          debugLog("[Chat] Chunk received:", chunk);
          const lines = chunk.split("\n");
          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const data = line.slice(6).trim();
            if (data === "[DONE]") {
              streamDone = true;
              break;
            }
            try {
              const parsed = JSON.parse(data);
              debugLog("[Chat] Parsed data:", parsed);
              if (parsed.content) {
                let content = parsed.content;
                assistantMsg += content;
                setMessages((prev) => {
                  debugLog(
                    "[Chat] Updating messages, prev length:",
                    prev.length,
                    "assistantMsgAdded:",
                    assistantMsgAdded
                  );
                  const lastMsg = prev[prev.length - 1];
                  if (
                    lastMsg?.role === "assistant" &&
                    lastMsg.id === 0 &&
                    assistantMsgAdded
                  ) {
                    return [
                      ...prev.slice(0, -1),
                      { ...lastMsg, content: assistantMsg },
                    ];
                  } else if (!assistantMsgAdded) {
                    assistantMsgAdded = true;
                    return [
                      ...prev,
                      {
                        id: 0,
                        conversation_id: convId,
                        role: "assistant",
                        content: assistantMsg,
                        created_at: new Date().toISOString(),
                      },
                    ];
                  }
                  return prev;
                });
                scrollToBottom();
              }
              if (parsed.done) {
                streamDone = true;
                const doneEvent: DoneEvent = parsed;
                setMessages((prev) => {
                  const idx = prev.findIndex(
                    (m) => m.role === "assistant" && m.id === 0
                  );
                  if (idx === -1) return prev;
                  const updated = mergeDoneMetadata(prev[idx], doneEvent);
                  if (updated === prev[idx]) return prev;
                  return [
                    ...prev.slice(0, idx),
                    updated,
                    ...prev.slice(idx + 1),
                  ];
                });
              }
            } catch (error) {
              message.error("流式响应解析失败");
              if (process.env.NODE_ENV === "development") {
                console.error("Stream parsing error:", error);
              }
            }
          }
        }
        debugLog(
          "[Chat] Stream complete, assistantMsg:",
          assistantMsg.substring(0, 100)
        );
      } catch (error) {
        message.error("发送消息失败");
      } finally {
        setStreaming(false);
      }
    },
    [currentConv, streaming, message, debugLog, scrollToBottom]
  );

  // 入口 — 输入框 send 按钮 / Enter 触发
  const handleSend = useCallback(
    async (
      userMsg: string,
      msgAttachments: AttachmentRef[],
      toggles: FeatureToggles,
      onResetInput: () => void
    ) => {
      const trimmed = userMsg.trim();
      if (!trimmed || streaming) return;
      if (!currentConv) {
        message.warning("请先创建或选择一个对话");
        return;
      }
      // 保存当前值,弹窗期间不丢失
      setPendingMessage(trimmed);
      setPendingAttachments([...msgAttachments]);

      try {
        const token = localStorage.getItem("access_token") || "";
        const recs = await chatApi.recommendSkills(trimmed, token);
        if (recs.length > 0) {
          setRecommendedSkills(recs);
          setSelectedRecommendIds(recs.slice(0, 5).map((r) => r.skill_id));
          setRecommendModalOpen(true);
          onResetInput();
        } else {
          onResetInput();
          await doSend(trimmed, [], msgAttachments, toggles);
        }
      } catch {
        onResetInput();
        await doSend(trimmed, [], msgAttachments, toggles);
      }
    },
    [currentConv, streaming, message, doSend]
  );

  const confirmRecommend = useCallback(
    async (toggles: FeatureToggles) => {
      const ids = selectedRecommendIds;
      setRecommendModalOpen(false);
      const msg = pendingMessage;
      const atts = [...pendingAttachments];
      setPendingMessage("");
      setPendingAttachments([]);
      await doSend(msg, ids, atts, toggles);
    },
    [selectedRecommendIds, pendingMessage, pendingAttachments, doSend]
  );

  const cancelRecommend = useCallback(
    async (toggles: FeatureToggles) => {
      setRecommendModalOpen(false);
      const msg = pendingMessage;
      const atts = [...pendingAttachments];
      setPendingMessage("");
      setPendingAttachments([]);
      await doSend(msg, [], atts, toggles);
    },
    [pendingMessage, pendingAttachments, doSend]
  );

  const toggleRecommend = useCallback(
    (skillId: number) => {
      setSelectedRecommendIds((prev) => {
        const checked = prev.includes(skillId);
        if (checked) return prev.filter((id) => id !== skillId);
        if (prev.length >= 5) {
          message.warning("最多选5个技能");
          return prev;
        }
        return [...prev, skillId];
      });
    },
    [message]
  );

  // 新建 conv / 切到空 conv 时清空消息
  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  return {
    messages,
    streaming,
    recommendModalOpen,
    recommendedSkills,
    selectedRecommendIds,
    pendingMessage,
    pendingAttachments,
    messagesEndRef,
    chatContainerRef,
    handleSend,
    confirmRecommend,
    cancelRecommend,
    toggleRecommend,
    clearMessages,
    scrollToBottom,
  };
}