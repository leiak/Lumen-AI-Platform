"use client";

import { Spin } from "antd";
import type { RefObject } from "react";
import type { Agent } from "@/types/api";
import type { Conversation, Message } from "@/types/chat";
import { AgentKBBanner } from "@/components/agent/AgentKBBanner";
import { MessageBubble } from "./MessageBubble";

/**
 * M30b-style: 消息流 + Agent KB banner + streaming indicator + 滚到底部。
 *
 * Props:
 * - messages / streaming — 来自 useChatMessages
 * - currentConv / agents — banner 需要匹配当前 agent 的 KB
 * - bannerDismissedForConv / onDismissBanner — dismiss state 由 page 提供
 * - chatContainerRef / messagesEndRef — scroll 锚点
 */
export function ChatMessages(props: {
  currentConv: Conversation | null;
  agents: Agent[];
  messages: Message[];
  streaming: boolean;
  bannerDismissedForConv: Set<number>;
  onDismissBanner: (convId: number) => void;
  chatContainerRef: RefObject<HTMLDivElement>;
  messagesEndRef: RefObject<HTMLDivElement>;
}) {
  const {
    currentConv,
    agents,
    messages,
    streaming,
    bannerDismissedForConv,
    onDismissBanner,
    chatContainerRef,
    messagesEndRef,
  } = props;

  return (
    <div
      ref={chatContainerRef}
      style={{ flex: 1, overflowY: "auto", padding: 24, minWidth: 600 }}
    >
      {/* M21 T19: Agent KB banner — session-only dismissed state. Only
          shown when the current conv has an agent bound to >= 1 KB. */}
      {currentConv &&
        (() => {
          const agent = agents.find((a) => a.id === currentConv.agent_id);
          const kbs = agent?.knowledge_bases;
          if (!kbs || kbs.length === 0) return null;
          if (bannerDismissedForConv.has(currentConv.id)) return null;
          return (
            <AgentKBBanner
              agent={agent!}
              onClose={() => onDismissBanner(currentConv.id)}
            />
          );
        })()}
      {!currentConv ? (
        <div style={{ textAlign: "center", color: "#999", marginTop: 100 }}>
          <p>选择一个对话或创建新对话开始聊天</p>
        </div>
      ) : messages.length === 0 ? (
        <div style={{ textAlign: "center", color: "#999", marginTop: 100 }}>
          <p>发送消息开始对话</p>
        </div>
      ) : (
        messages.map((msg, idx) => {
          return (
            <div
              key={idx}
              style={{
                marginBottom: 16,
                display: "flex",
                justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
              }}
            >
              <div style={{ maxWidth: "80%", minWidth: 150 }}>
                <MessageBubble message={msg} />
              </div>
            </div>
          );
        })
      )}
      {streaming && (
        <div
          style={{
            marginBottom: 16,
            display: "flex",
            justifyContent: "flex-start",
          }}
        >
          <div
            style={{
              padding: "12px 16px",
              borderRadius: 12,
              background: "#f0f0f0",
            }}
          >
            <Spin size="small" /> AI思考中...
          </div>
        </div>
      )}
      <div ref={messagesEndRef} />
    </div>
  );
}