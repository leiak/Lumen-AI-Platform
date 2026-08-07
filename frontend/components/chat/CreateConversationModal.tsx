"use client";

import { Modal, Select } from "antd";
import type { Agent } from "@/types/api";

/**
 * M30b-style: 新建对话 modal —— 让用户选本次对话绑哪个 Agent(可选)。
 *
 * 行为透传:`createAgentId` 由 useChatAgents 管理,这里只展示 + 转发 onChange。
 */
export function CreateConversationModal(props: {
  open: boolean;
  creating: boolean;
  agents: Agent[];
  agentPickerLoading: boolean;
  createAgentId: number | null;
  onChangeCreateAgentId: (id: number | null) => void;
  onOk: () => void;
  onCancel: () => void;
}) {
  const {
    open,
    creating,
    agents,
    agentPickerLoading,
    createAgentId,
    onChangeCreateAgentId,
    onOk,
    onCancel,
  } = props;

  return (
    <Modal
      title="新建对话"
      open={open}
      onCancel={onCancel}
      onOk={onOk}
      okText="创建"
      cancelText="取消"
      confirmLoading={creating}
    >
      <div style={{ marginBottom: 8 }}>选择本次对话使用的 Agent:</div>
      <Select
        style={{ width: "100%" }}
        value={createAgentId ?? 0}
        onChange={(v) => onChangeCreateAgentId(v ? v : null)}
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
          <a
            href="/dashboard/agent"
            target="_blank"
            rel="noopener noreferrer"
            style={{ marginLeft: 4 }}
          >
            AI Agent 页面
          </a>
          创建一个。
        </div>
      )}
    </Modal>
  );
}