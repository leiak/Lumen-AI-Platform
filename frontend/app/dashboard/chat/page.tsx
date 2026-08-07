"use client";

import { useState } from "react";
import { Select } from "antd";

import { ChatSidebar } from "@/components/chat/ChatSidebar";
import { ChatMessages } from "@/components/chat/ChatMessages";
import { ChatInput } from "@/components/chat/ChatInput";
import { SkillPickerModal } from "@/components/chat/SkillPickerModal";
import { RecommendSkillsModal } from "@/components/chat/RecommendSkillsModal";
import { CreateConversationModal } from "@/components/chat/CreateConversationModal";
import { FeatureTogglesState } from "@/components/chat/FeatureToggles";
import { PptConfigModal } from "@/components/chat/PptConfigModal";

import { useChatConversations } from "./hooks/useChatConversations";
import { useChatAgents } from "./hooks/useChatAgents";
import { useChatSkills } from "./hooks/useChatSkills";
import { useChatAttachments } from "./hooks/useChatAttachments";
import { useChatMessages } from "./hooks/useChatMessages";

/**
 * M30b-style: 编排层。938 → ~210 行。
 *
 * 只负责 hook 调用 + 组件拼装,无业务逻辑。所有 state/handler 都被封装进
 * ``hooks/`` 子目录的 5 个 hook(各管一组 state + callback);所有 UI 子树被
 * 拆到 ``components/chat/`` 子目录的 6 个组件(纯展示)。
 *
 * 仍然保留在 page.tsx 的 state:
 * - input — 当前输入框文本,生命周期 = 组件挂载,不适合抽 hook
 * - toggles — FeatureToggles state(skillIds / thinking / web search),
 *   直接绑 FeatureToggles 组件,抽 hook 没收益
 * - pptModalOpen — PPT 生成 modal 单 state
 */
export default function ChatPage() {
  const conversations = useChatConversations();
  const agents = useChatAgents();
  const skills = useChatSkills();
  const attachments = useChatAttachments();
  const messages = useChatMessages(conversations.currentConv);

  const [toggles, setToggles] = useState<FeatureTogglesState>({
    enableThinking: false,
    enableWebSearch: false,
    skillIds: [],
  });
  const [input, setInput] = useState("");
  const [pptModalOpen, setPptModalOpen] = useState(false);

  // --- handler assembly: hooks 之间的事件桥 ---
  // 切 agent:flight 成功 → 应用更新到 conv + 重置 banner dismissed。
  // 必须走 handleSwitchAgent 闭包外侧,因为 useChatAgents 不感知 banner state。
  const handleSwitchAgent = async (v: unknown) => {
    if (!conversations.currentConv) return;
    const convId = conversations.currentConv.id;
    const newAgentId = (v ?? null) as number | null;
    const updated = await agents.switchAgentForConv(
      convId,
      conversations.currentConv,
      newAgentId
    );
    if (updated) {
      conversations.applyUpdatedConv(updated);
      conversations.resetBannerDismissed();
    }
  };

  // 打开技能选择器:传当前 toggles.skillIds 作为 draft 初值
  const handleOpenSkillPicker = () => {
    skills.openPicker(toggles.skillIds);
  };

  // 技能选择器 OK:把 draft 灌到 toggles.skillIds(限 5 个)
  const handleCommitSkillPicker = () => {
    setToggles((t) => ({
      ...t,
      skillIds: skills.draftSkillIds.slice(0, 5),
    }));
    skills.closePicker();
  };

  // FeatureToggles 上的"技能"按钮 → 打开 picker
  // (上面 handleOpenSkillPicker 已经在 FeatureToggles.onOpenSkillPicker 链路)

  // 点击发送 → 触发技能推荐 / 直接发
  const handleSend = async () => {
    await messages.handleSend(input, attachments.attachments, toggles, () => {
      setInput("");
      attachments.clearAttachments();
      setToggles({ enableThinking: false, enableWebSearch: false, skillIds: [] });
    });
  };

  // 推荐 modal 取消 / 确认 → 走 doSend,弹窗期间已存的 input/attachments 不变
  const handleConfirmRecommend = async () => {
    setInput("");
    attachments.clearAttachments();
    setToggles({ enableThinking: false, enableWebSearch: false, skillIds: [] });
    await messages.confirmRecommend(toggles);
  };
  const handleCancelRecommend = async () => {
    setInput("");
    attachments.clearAttachments();
    setToggles({ enableThinking: false, enableWebSearch: false, skillIds: [] });
    await messages.cancelRecommend(toggles);
  };

  // 删除对话后:如果删的是当前选中且没有剩余,清空消息区
  const handleDeleteConversation = async (id: number) => {
    await conversations.deleteConversation(id);
    // 用 conversations.conversations(刚刚 refetch 过的列表)判断
    const remaining = conversations.conversations.filter((c) => c.id !== id);
    if (remaining.length === 0) {
      messages.clearMessages();
    }
  };

  // 新建对话成功 → 清空消息区 + 关 modal
  const handleConfirmCreate = async () => {
    const newConv = await conversations.createConversation(agents.createAgentId);
    if (newConv) {
      agents.closeCreateModal();
      messages.clearMessages();
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
      <ChatSidebar
        conversations={conversations.conversations}
        currentConv={conversations.currentConv}
        creating={conversations.creating}
        deletingId={conversations.deletingId}
        onSelect={conversations.selectConv}
        onDelete={handleDeleteConversation}
        onCreate={agents.openCreateModal}
      />

      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          minWidth: 0,
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "12px 24px",
            borderBottom: "1px solid #f0f0f0",
            background: "#fff",
          }}
        >
          <strong>
            {conversations.currentConv?.title || "选择或创建对话"}
          </strong>
        </div>

        {/* 顶部 Agent 切换器 */}
        {conversations.currentConv && (
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
              value={conversations.currentConv.agent_id ?? null}
              onChange={handleSwitchAgent}
              loading={
                agents.updatingAgentId === conversations.currentConv.id ||
                agents.agentPickerLoading
              }
              options={[
                { value: null, label: "默认 (使用 tenant 默认模型)" },
                ...agents.agents.map((a) => ({ value: a.id, label: a.name })),
              ]}
              placeholder="选择 Agent"
              optionFilterProp="label"
              showSearch
            />
          </div>
        )}

        <ChatMessages
          currentConv={conversations.currentConv}
          agents={agents.agents}
          messages={messages.messages}
          streaming={messages.streaming}
          bannerDismissedForConv={conversations.bannerDismissedForConv}
          onDismissBanner={conversations.dismissBannerForConv}
          chatContainerRef={messages.chatContainerRef}
          messagesEndRef={messages.messagesEndRef}
        />

        <ChatInput
          input={input}
          onChangeInput={setInput}
          toggles={toggles}
          onChangeToggles={setToggles}
          onPickFile={attachments.triggerPick}
          onUpload={attachments.handleFileChange}
          onOpenSkillPicker={handleOpenSkillPicker}
          onOpenPptConfig={() => setPptModalOpen(true)}
          attachments={attachments.attachments}
          onRemoveAttachment={attachments.removeAttachment}
          uploading={attachments.uploading}
          streaming={messages.streaming}
          hasConv={!!conversations.currentConv}
          onSend={handleSend}
          fileInputRef={attachments.fileInputRef}
        />
      </div>

      <SkillPickerModal
        open={skills.pickerOpen}
        installedSkills={skills.installedSkills}
        draftSkillIds={skills.draftSkillIds}
        onChangeDraft={skills.setDraft}
        onOk={handleCommitSkillPicker}
        onCancel={skills.closePicker}
      />

      <RecommendSkillsModal
        open={messages.recommendModalOpen}
        pendingMessage={messages.pendingMessage}
        recommendedSkills={messages.recommendedSkills}
        selectedRecommendIds={messages.selectedRecommendIds}
        onToggleRecommend={messages.toggleRecommend}
        onCancel={handleCancelRecommend}
        onConfirm={handleConfirmRecommend}
      />

      <CreateConversationModal
        open={agents.createOpen}
        creating={conversations.creating}
        agents={agents.agents}
        agentPickerLoading={agents.agentPickerLoading}
        createAgentId={agents.createAgentId}
        onChangeCreateAgentId={agents.setCreateAgentId}
        onOk={handleConfirmCreate}
        onCancel={agents.closeCreateModal}
      />

      <PptConfigModal
        open={pptModalOpen}
        conversationId={conversations.currentConv?.id ?? 0}
        conversationTitle={conversations.currentConv?.title}
        onClose={() => setPptModalOpen(false)}
      />
    </div>
  );
}