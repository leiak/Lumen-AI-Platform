"use client";

import { useState, useEffect, useRef } from "react";
import { Input, Button, List, Spin, Modal, Select, Popconfirm, App, Tag, Tooltip, Badge } from "antd";
import { SendOutlined, PlusOutlined, DeleteOutlined } from "@ant-design/icons";
import { chatApi, type UploadResult, type SkillRecommendation } from "@/services/chat";
import { skillsApi, type InstalledSkill } from "@/services/skills";
import { agentApi } from "@/services/agent";
import type { Message, Conversation, AttachmentRef } from "@/types/chat";
import type { Agent } from "@/types/api";
import { MessageBubble } from "@/components/chat/MessageBubble";
import { FeatureToggles, type FeatureTogglesState } from "@/components/chat/FeatureToggles";
import { AttachmentChip } from "@/components/chat/AttachmentChip";
import { PptConfigModal } from "@/components/chat/PptConfigModal";
import { AgentKBBanner } from "@/components/agent/AgentKBBanner";
import { mergeDoneMetadata, type DoneEvent } from "@/lib/chat-sse-utils";

export default function ChatPage() {
  const { message } = App.useApp();
  // M30 P0-3: dev-only debug log helper — silences streaming/parse
  // noise in production (per MEMORY 2026-06-07 antd v5 + Next.js
  // strict-mode console.* guidance).
  const DEBUG = process.env.NODE_ENV === "development";
  const debugLog = (...args: unknown[]) => {
    if (DEBUG) console.log(...args);
  };
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentConv, setCurrentConv] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [creating, setCreating] = useState(false);
  const [toggles, setToggles] = useState<FeatureTogglesState>({
    enableThinking: false,
    enableWebSearch: false,
    skillIds: [],
  });
  const [skillPickerOpen, setSkillPickerOpen] = useState(false);
  const [draftSkillIds, setDraftSkillIds] = useState<number[]>([]);
  const [installedSkills, setInstalledSkills] = useState<{ value: number; label: string; category: string }[]>([]);
  const [attachments, setAttachments] = useState<AttachmentRef[]>([]);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentPickerLoading, setAgentPickerLoading] = useState(false);
  const [updatingAgentId, setUpdatingAgentId] = useState<number | null>(null);
  // 新建对话 modal state
  const [createOpen, setCreateOpen] = useState(false);
  const [createAgentId, setCreateAgentId] = useState<number | null>(null);
  // M21 T19: session-only dismissed state for the AgentKBBanner. Keyed by
  // conversation id. Reset on conv switch / create / agent switch so the
  // banner re-appears for the new context.
  const [bannerDismissedForConv, setBannerDismissedForConv] = useState<Set<number>>(
    () => new Set()
  );
  // 技能推荐弹窗 state
  const [recommendModalOpen, setRecommendModalOpen] = useState(false);
  const [recommendedSkills, setRecommendedSkills] = useState<SkillRecommendation[]>([]);
  const [pendingMessage, setPendingMessage] = useState("");
  const [pendingAttachments, setPendingAttachments] = useState<AttachmentRef[]>([]);
  // 用户在推荐弹窗中最终选择的 skillIds（用于最终发送）
  const [selectedRecommendIds, setSelectedRecommendIds] = useState<number[]>([]);
  // M35: PPT 生成弹窗
  const [pptModalOpen, setPptModalOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, 100);
  };

  const handlePickFile = () => fileInputRef.current?.click();

  const handleFileSelected = async (
    e: React.ChangeEvent<HTMLInputElement>
  ) => {
    const file = e.target.files?.[0];
    // Reset input value so picking the same file twice still triggers onChange
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    try {
      const token = localStorage.getItem("access_token") || "";
      const result: UploadResult = await chatApi.uploadAttachment(file, token);
      setAttachments((prev) => [
        ...prev,
        {
          file_id: result.file_id,
          name: result.name,
          size: result.size,
          mime_type: result.mime_type,
          content_text: result.content_text,
        },
      ]);
      message.success(`已添加附件:${result.name}`);
    } catch (err: any) {
      message.error(`上传失败:${err?.message || err}`);
    } finally {
      setUploading(false);
    }
  };

  const fetchConversations = async () => {
    try {
      const res = await chatApi.listConversations();
      if (res.data.code === 200) {
        setConversations(res.data.data || []);
      }
    } catch (error) {
      message.error("加载对话列表失败");
    }
  };

  const fetchMessages = async (convId: number) => {
    try {
      const res = await chatApi.getMessages(convId);
      if (res.data.code === 200) {
        setMessages(res.data.data || []);
        scrollToBottom();
      }
    } catch (error) {
      message.error("加载消息失败");
    }
  };

  const fetchAgents = async () => {
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
  };

  const handleDeleteConversation = async (id: number) => {
    setDeletingId(id);
    try {
      const res = await chatApi.deleteConversation(id);
      if (res.data.code === 200) {
        message.success("删除成功");
        // refetch 拿最新列表(按 updated_at desc 已排好序)
        await fetchConversations();
        // 删的是当前选中 → 跳到最近一个。
        // 注意:`conversations` 是 closure 旧值(React state 异步,fetchConversations 调用的
        // setConversations 还没生效);但因为后端已过滤已软删,旧列表减一 == 新列表,
        // 所以用 conversations.filter(c => c.id !== id) 得到的就是新列表的内容。
        if (currentConv?.id === id) {
          const remaining = conversations.filter((c) => c.id !== id);
          if (remaining.length > 0) {
            setCurrentConv(remaining[0]);
            // getMessages(remaining[0].id) 会在 currentConv effect 里自动触发
          } else {
            setCurrentConv(null);
            setMessages([]);
          }
        }
      } else {
        message.error(res.data.message || "删除失败");
      }
    } catch (err) {
      message.error("删除失败");
    } finally {
      setDeletingId(null);
    }
  };

  useEffect(() => {
    fetchConversations();
    fetchAgents();
  }, []);

  useEffect(() => {
    if (currentConv) {
      fetchMessages(currentConv.id);
    }
  }, [currentConv]);

  useEffect(() => {
    if (!skillPickerOpen) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await skillsApi.listInstalled(1, 50);
        if (cancelled) return;
        if (res.data.code === 200) {
          // listInstalled returns a PaginatedResponse — `data` is the array itself,
          // not an object with another nested `data` field. Older code read
          // `res.data.data?.data` and silently got an empty list.
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
        message.error("加载已装技能失败");
      }
    })();
    return () => { cancelled = true; };
  }, [skillPickerOpen]);

  const handleCreateConversation = () => {
    setCreateAgentId(null);
    setCreateOpen(true);
  };

  const handleConfirmCreate = async () => {
    setCreating(true);
    try {
      const res = await chatApi.createConversation({
        agent_id: createAgentId ?? undefined,
      });
      if (res.data.code === 200) {
        const newConv = res.data.data;
        setConversations([newConv, ...conversations]);
        setCurrentConv(newConv);
        setMessages([]);
        setCreateOpen(false);
        // M21 T19: 新对话 — 重置 dismissed 让 banner 重新出现
        setBannerDismissedForConv(new Set());
      } else {
        message.error(res.data.message || "创建对话失败");
      }
    } catch (err) {
      message.error("创建对话失败");
    } finally {
      setCreating(false);
    }
  };

  // 顶部 Agent 切换器:改写某个 conv 的 agent_id。
  // 必须独立成函数——inline arrow 会 closure-capture currentConv,导致在
  // PATCH 飞行期间用户切到别的 conv 时,旧 conv 的响应回来把新选中的 conv
  // 覆盖掉(见 2026-06-08 评审 Important #1)。
  const handleSwitchAgent = async (v: unknown) => {
    if (!currentConv) return;
    const newAgentId = (v ?? null) as number | null;
    // 在请求发出前 snapshot 目标 convId,后面用这个常量去匹配响应是否仍然
    // 指向用户当前在看的会话。
    const convId = currentConv.id;
    setUpdatingAgentId(convId);
    try {
      const res = await chatApi.updateConversation(convId, {
        agent_id: newAgentId,
      });
      if (res.data.code === 200) {
        const updated = res.data.data;
        // 后端契约是 200 时 data 非空,但保险起见守一下——null 时直接报错退出,
        // 否则下面 updated.id 会抛 "Cannot read properties of null"。
        if (!updated) {
          message.error("服务器返回为空");
          return;
        }
        // 列表里原地替换这条 conv——functional update 不会读 stale 闭包。
        setConversations((prev) =>
          prev.map((c) => (c.id === updated.id ? updated : c))
        );
        // 只有当用户**当前**仍停在同一个 conv 上时,才把指针更新到新记录。
        // 用 functional update 拿到的是 live state,不是 handler 创建时
        // 的闭包值,这样能正确处理"切 agent → 切 conv → 旧 PATCH 回来"的竞态。
        setCurrentConv((prev) => (prev?.id === convId ? updated : prev));
        // M21 T19: 切 agent → 重置 dismissed 让 banner 用新 agent 的 KB 列表重新出现
        setBannerDismissedForConv(new Set());
        const agentName = newAgentId
          ? agents.find((a) => a.id === newAgentId)?.name || "该 Agent"
          : "默认模型";
        message.success(`已切换到 ${agentName},后续回复风格会变`);
      } else {
        message.error(res.data.message || "切换失败");
      }
    } catch (err) {
      message.error("切换失败");
    } finally {
      setUpdatingAgentId(null);
    }
  };

  const handleOpenSkillPicker = () => {
    setDraftSkillIds(toggles.skillIds);
    setSkillPickerOpen(true);
  };

  const handleCommitSkillPicker = () => {
    setToggles((t) => ({ ...t, skillIds: draftSkillIds.slice(0, 5) }));
    setSkillPickerOpen(false);
  };

  const handleOpenPptConfig = () => {
    if (!currentConv) {
      return;
    }
    setPptModalOpen(true);
  };

  // 拦截发送：先调用技能推荐 API，有结果弹确认框
  const handleSend = async () => {
    const userMsg = input.trim();
    if (!userMsg || streaming) return;
    if (!currentConv) {
      message.warning("请先创建或选择一个对话");
      return;
    }

    // 保存当前值，弹窗期间不丢失
    setPendingMessage(userMsg);
    setPendingAttachments([...attachments]);

    try {
      const token = localStorage.getItem("access_token") || "";
      const recs = await chatApi.recommendSkills(userMsg, token);
      if (recs.length > 0) {
        setRecommendedSkills(recs);
        setSelectedRecommendIds(recs.slice(0, 5).map(r => r.skill_id));
        setRecommendModalOpen(true);
      } else {
        // 无推荐直接发送
        setInput("");
        setAttachments([]);
        setToggles({ enableThinking: false, enableWebSearch: false, skillIds: [] });
        await doSend(userMsg, [], [...attachments]);
      }
    } catch {
      // 推荐失败，直接发送
      setInput("");
      setAttachments([]);
      setToggles({ enableThinking: false, enableWebSearch: false, skillIds: [] });
      await doSend(userMsg, [], [...attachments]);
    }
  };

  // 实际发送逻辑
  const doSend = async (
    userMsg: string,
    finalSkillIds: number[],
    msgAttachments: AttachmentRef[]
  ) => {
    if (!userMsg || streaming) return;
    if (!currentConv) {
      message.warning("请先创建或选择一个对话");
      return;
    }

    const convId = currentConv.id;
    setInput("");
    setAttachments([]);
    setToggles({ enableThinking: false, enableWebSearch: false, skillIds: [] });
    setStreaming(true);

    // Optimistically add user message
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
    setMessages(prev => [...prev, tempUserMsg]);
    scrollToBottom();

    try {
      const token = localStorage.getItem("access_token") || "";
      debugLog("[Chat] Sending request:", { message: userMsg, conversation_id: convId });
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

      if (response) {
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
            if (line.startsWith("data: ")) {
              const data = line.slice(6).trim();
              if (data === "[DONE]") {
                streamDone = true;
                break;
              }
              try {
                const parsed = JSON.parse(data);
                debugLog("[Chat] Parsed data:", parsed);
                if (parsed.content) {
                  // Keep thinking content for display
                  let content = parsed.content;
                  assistantMsg += content;

                  // Update messages with streaming content
                  setMessages(prev => {
                    debugLog("[Chat] Updating messages, prev length:", prev.length, "assistantMsgAdded:", assistantMsgAdded);
                    const lastMsg = prev[prev.length - 1];
                    debugLog("[Chat] Last message role:", lastMsg?.role, "id:", lastMsg?.id);

                    // Only update if last message is our streaming assistant message
                    if (lastMsg?.role === "assistant" && lastMsg.id === 0 && assistantMsgAdded) {
                      // Update existing streaming message
                      debugLog("[Chat] Updating existing assistant message");
                      return [...prev.slice(0, -1), { ...lastMsg, content: assistantMsg }];
                    } else if (!assistantMsgAdded) {
                      // Add new assistant message for the first chunk
                      debugLog("[Chat] Adding new assistant message");
                      assistantMsgAdded = true;
                      return [...prev, {
                        id: 0,
                        conversation_id: convId,
                        role: "assistant",
                        content: assistantMsg,
                        created_at: new Date().toISOString(),
                      }];
                    }
                    return prev;
                  });
                  scrollToBottom();
                }
                if (parsed.done) {
                  streamDone = true;
                  // Patch the streaming assistant message with the final
                  // metadata (search_status, sources) so the MessageBubble
                  // can render the search-failure notice and citations
                  // without a DB re-fetch.
                  const doneEvent: DoneEvent = parsed;
                  setMessages((prev) => {
                    const idx = prev.findIndex(
                      (m) => m.role === "assistant" && m.id === 0
                    );
                    if (idx === -1) return prev;
                    const updated = mergeDoneMetadata(prev[idx], doneEvent);
                    if (updated === prev[idx]) return prev; // no-op
                    return [...prev.slice(0, idx), updated, ...prev.slice(idx + 1)];
                  });
                  if (parsed.conversation_id && currentConv?.id !== parsed.conversation_id) {
                    // New conversation was created
                    fetchConversations();
                  }
                }
              } catch (error) {
                // M30 P0-3: surface stream parse errors to the user —
                // they previously only landed in devtools.
                message.error("流式响应解析失败");
                if (process.env.NODE_ENV === "development") {
                  console.error("Stream parsing error:", error);
                }
              }
            }
          }
        }
        debugLog("[Chat] Stream complete, assistantMsg:", assistantMsg.substring(0, 100));
      } else {
        message.error("发送消息失败:服务器未返回响应");
      }
    } catch (error) {
      message.error("发送消息失败");
    } finally {
      setStreaming(false);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        width: "80vw",
        height: "80vh",
        margin: "10vh auto 0",
        minWidth: 1000,
        background: "#fff",
        borderRadius: 8,
        boxShadow: "0 4px 24px rgba(0,0,0,0.08)",
        overflow: "hidden",
      }}
    >
      {/* Conversation List Sidebar */}
      <div style={{ width: 300, minWidth: 300, borderRight: "1px solid #f0f0f0", display: "flex", flexDirection: "column", background: "#fafafa" }}>
        <div style={{ padding: 16 }}>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            block
            onClick={handleCreateConversation}
            loading={creating}
          >
            新建对话
          </Button>
        </div>
        <div style={{ flex: 1, overflowY: "auto" }}>
          <List
            dataSource={conversations}
            renderItem={(item) => (
              <List.Item
                key={item.id}
                onClick={() => {
                  if (currentConv?.id !== item.id) {
                    // M21 T19: 切到另一个 conv → 重置 dismissed 让 banner 用新 conv 的 agent 重新出现
                    setBannerDismissedForConv(new Set());
                  }
                  setCurrentConv(item);
                }}
                actions={[
                  <Popconfirm
                    key="delete"
                    title="确认删除该对话?"
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    onConfirm={(e) => {
                      e?.stopPropagation();
                      handleDeleteConversation(item.id);
                    }}
                    onCancel={(e) => e?.stopPropagation()}
                  >
                    <Button
                      type="text"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      loading={deletingId === item.id}
                      aria-label="删除"
                      onClick={(e) => e.stopPropagation()}
                    />
                  </Popconfirm>,
                ]}
                style={{
                  cursor: "pointer",
                  background: currentConv?.id === item.id ? "#e6f7ff" : "transparent",
                  padding: "12px 16px",
                }}
              >
                <List.Item.Meta
                  title={
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis" }}>
                        {item.title || "新对话"}
                      </span>
                      {item.agent_id && item.agent_name && (
                        <Tooltip title={`Agent: ${item.agent_name}`}>
                          <Tag color="blue" style={{ marginRight: 0 }}>
                            {item.agent_name.slice(0, 8)}
                          </Tag>
                        </Tooltip>
                      )}
                    </div>
                  }
                  description={new Date(item.updated_at).toLocaleDateString()}
                />
              </List.Item>
            )}
          />
        </div>
      </div>

      {/* Chat Area */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {/* Header */}
        <div style={{ padding: "12px 24px", borderBottom: "1px solid #f0f0f0", background: "#fff" }}>
          <strong>{currentConv?.title || "选择或创建对话"}</strong>
        </div>

        {/* 顶部 Agent 切换器 */}
        {currentConv && (
          <div
            style={{
              padding: "8px 24px",
              borderBottom: "1px solid #f0f0f0",
              background: "#fafafa",
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <span style={{ color: "#666", fontSize: 13 }}>Agent:</span>
            <Select
              style={{ minWidth: 240 }}
              value={currentConv.agent_id ?? null}
              onChange={handleSwitchAgent}
              loading={updatingAgentId === currentConv.id || agentPickerLoading}
              options={[
                { value: null, label: "默认 (使用 tenant 默认模型)" },
                ...agents.map((a) => ({ value: a.id, label: a.name })),
              ]}
              placeholder="选择 Agent"
              optionFilterProp="label"
              showSearch
            />
          </div>
        )}

        {/* Messages */}
        <div
          ref={chatContainerRef}
          style={{ flex: 1, overflowY: "auto", padding: 24, minWidth: 600 }}
        >
          {/* M21 T19: Agent KB banner — session-only dismissed state. Only
              shown when the current conv has an agent bound to >= 1 KB. */}
          {currentConv && (() => {
            const agent = agents.find((a) => a.id === currentConv.agent_id);
            const kbs = agent?.knowledge_bases;
            if (!kbs || kbs.length === 0) return null;
            if (bannerDismissedForConv.has(currentConv.id)) return null;
            return (
              <AgentKBBanner
                agent={agent!}
                onClose={() => {
                  setBannerDismissedForConv(
                    (prev) => new Set([...prev, currentConv.id])
                  );
                }}
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
                <div
                  style={{
                    maxWidth: "80%",
                    minWidth: 150,
                  }}
                >
                  <MessageBubble message={msg} />
                </div>
              </div>
              );
            })
          )}
          {streaming && (
            <div style={{ marginBottom: 16, display: "flex", justifyContent: "flex-start" }}>
              <div style={{ padding: "12px 16px", borderRadius: 12, background: "#f0f0f0" }}>
                <Spin size="small" /> AI思考中...
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div style={{ padding: 16, borderTop: "1px solid #f0f0f0", background: "#fff" }}>
          <input
            ref={fileInputRef}
            type="file"
            style={{ display: "none" }}
            onChange={handleFileSelected}
            accept=".txt,.md,.pdf,.docx,.pptx,.xlsx"
          />
          <FeatureToggles
            value={toggles}
            onChange={setToggles}
            onPickFile={handlePickFile}
            onOpenSkillPicker={handleOpenSkillPicker}
            onOpenPptConfig={handleOpenPptConfig}
            hasAttachments={attachments.length > 0}
            disabled={!currentConv || streaming || uploading}
          />
          {attachments.length > 0 && (
            <div style={{ marginBottom: 8, display: "flex", flexWrap: "wrap" }}>
              {attachments.map((a) => (
                <AttachmentChip
                  key={a.file_id}
                  attachment={a}
                  onRemove={() =>
                    setAttachments((prev) =>
                      prev.filter((x) => x.file_id !== a.file_id)
                    )
                  }
                />
              ))}
            </div>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onPressEnter={handleSend}
              placeholder={
                uploading
                  ? "上传中..."
                  : currentConv
                  ? "输入消息..."
                  : "请先选择对话"
              }
              disabled={!currentConv || streaming || uploading}
              size="large"
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSend}
              loading={streaming}
              disabled={!currentConv || uploading}
              size="large"
            />
          </div>
        </div>
        <Modal
          title="选择本次对话要启用的技能"
          open={skillPickerOpen}
          onCancel={() => setSkillPickerOpen(false)}
          onOk={handleCommitSkillPicker}
          okText="确定"
          cancelText="取消"
          width={520}
        >
          <Select
            mode="multiple"
            allowClear
            placeholder="选择已装技能(最多5个)"
            value={draftSkillIds}
            onChange={(v) => setDraftSkillIds((v as number[]).slice(0, 5))}
            options={installedSkills}
            optionFilterProp="label"
            style={{ width: "100%" }}
            maxTagCount={5}
          />
          {draftSkillIds.length >= 5 && (
            <div style={{ marginTop: 8, color: "#fa8c16" }}>
              已达 5 个上限。
            </div>
          )}
        </Modal>
        {/* 技能推荐确认弹窗 */}
        <Modal
          title="推荐技能 — 确认要启用哪些技能？"
          open={recommendModalOpen}
          onCancel={() => {
            setRecommendModalOpen(false);
            // 取消：直接发送，不带推荐技能
            setInput("");
            setAttachments([]);
            setToggles({ enableThinking: false, enableWebSearch: false, skillIds: [] });
            void doSend(pendingMessage, [], [...pendingAttachments]);
          }}
          footer={[
            <Button
              key="cancel"
              onClick={() => {
                setRecommendModalOpen(false);
                setInput("");
                setAttachments([]);
                setToggles({ enableThinking: false, enableWebSearch: false, skillIds: [] });
                void doSend(pendingMessage, [], [...pendingAttachments]);
              }}
            >
              不启用，直接发送
            </Button>,
            <Button
              key="confirm"
              type="primary"
              disabled={selectedRecommendIds.length === 0}
              onClick={() => {
                const ids = selectedRecommendIds;
                setRecommendModalOpen(false);
                setInput("");
                setAttachments([]);
                setToggles({ enableThinking: false, enableWebSearch: false, skillIds: [] });
                void doSend(pendingMessage, ids, [...pendingAttachments]);
              }}
            >
              确认启用 ({selectedRecommendIds.length})
            </Button>,
          ]}
          width={560}
        >
          <div style={{ marginBottom: 12, color: "#666", fontSize: 13 }}>
            根据你的消息「{pendingMessage.length > 40 ? pendingMessage.slice(0, 40) + "..." : pendingMessage}」，推荐以下技能（最多选5个）：
          </div>
          <div style={{ maxHeight: 360, overflowY: "auto" }}>
            {recommendedSkills.map((rec) => {
              const checked = selectedRecommendIds.includes(rec.skill_id);
              return (
                <div
                  key={rec.skill_id}
                  onClick={() => {
                    setSelectedRecommendIds((prev) => {
                      if (checked) return prev.filter(id => id !== rec.skill_id);
                      if (prev.length >= 5) {
                        message.warning("最多选5个技能");
                        return prev;
                      }
                      return [...prev, rec.skill_id];
                    });
                  }}
                  style={{
                    padding: "10px 12px",
                    marginBottom: 8,
                    border: `1px solid ${checked ? "#1890ff" : "#e8e8e8"}`,
                    borderRadius: 8,
                    cursor: "pointer",
                    background: checked ? "#f0f7ff" : "#fff",
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 10,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => {}}
                    style={{ marginTop: 3, flexShrink: 0 }}
                  />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
                      <span style={{ fontWeight: 600, fontSize: 14 }}>{rec.name}</span>
                      <Badge
                        count={`${Math.round(rec.confidence * 100)}%`}
                        style={{
                          backgroundColor: rec.confidence >= 0.7 ? "#52c41a" : rec.confidence >= 0.4 ? "#fa8c16" : "#999",
                          fontSize: 10,
                        }}
                        title={`匹配度: ${Math.round(rec.confidence * 100)}%`}
                      />
                      <Tag color={rec.match_type === "llm" ? "purple" : "cyan"} style={{ margin: 0, fontSize: 10 }}>
                        {rec.match_type === "llm" ? "AI 匹配" : "关键词"}
                      </Tag>
                    </div>
                    {rec.description && (
                      <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>
                        {rec.description}
                      </div>
                    )}
                    <div style={{ fontSize: 12, color: "#555" }}>
                      <span style={{ color: "#1890ff", fontWeight: 500 }}>理由：</span>{rec.reason}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </Modal>
        <Modal
          title="新建对话"
          open={createOpen}
          onCancel={() => setCreateOpen(false)}
          onOk={handleConfirmCreate}
          okText="创建"
          cancelText="取消"
          confirmLoading={creating}
        >
          <div style={{ marginBottom: 8 }}>选择本次对话使用的 Agent:</div>
          <Select
            style={{ width: "100%" }}
            value={createAgentId ?? 0}
            onChange={(v) => setCreateAgentId(v ? v : null)}
            placeholder="选择 Agent"
            allowClear
            loading={agentPickerLoading}
            options={[
              { value: 0, label: "默认 (使用 tenant 默认模型)" },
              ...agents.map((a) => ({
                value: a.id,
                label: `🤖 ${a.name}${a.description ? ` — ${a.description}` : ""}`,
              })),
            ]}
            optionFilterProp="label"
            showSearch
          />
          {agents.length === 0 && !agentPickerLoading && (
            <div style={{ marginTop: 8, color: "#999" }}>
              提示:当前 tenant 还没有 Agent,先到
              <a href="/dashboard/agent" target="_blank" rel="noopener noreferrer" style={{ marginLeft: 4 }}>AI Agent 页面</a>
              创建一个。
            </div>
          )}
        </Modal>
        {/* M35: PPT 生成配置弹框 */}
        <PptConfigModal
          open={pptModalOpen}
          conversationId={currentConv?.id ?? 0}
          conversationTitle={currentConv?.title}
          onClose={() => setPptModalOpen(false)}
        />
      </div>
    </div>
  );
}
