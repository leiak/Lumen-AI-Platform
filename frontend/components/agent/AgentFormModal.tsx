"use client";

import { useEffect, useState } from "react";
import {
  Modal,
  Form,
  Input,
  Select,
  Switch,
  InputNumber,
  Button,
  Divider,
  Space,
  message,
} from "antd";
import { agentApi, MEMORY_POLICIES, TOOL_CHOICE_MODES, type AgentCreatePayload } from "@/services/agent";
import type { ModelConfig } from "@/services/models";
import type { Agent } from "@/types/api";
import { MultiKBSelector } from "@/components/agent/MultiKBSelector";
import { KbRetrievalConfigFields } from "@/components/agent/KbRetrievalConfigFields";

const { TextArea } = Input;

const DEFAULT_VALUES: Partial<AgentCreatePayload> = {
  temperature: 0,
  memory_policy: "sliding_window",
  memory_window_size: 20,
  memory_max_tokens: 4000,
  memory_compression: false,
  tool_choice: "auto",
  tool_choice_required: false,
  allowed_tools: [],
  // M21: knowledge base binding defaults
  knowledge_base_ids: [],
  kb_retrieval_config: { top_k: 3, rrf_k: 30 },
};

export type AgentFormModalProps = {
  open: boolean;
  mode: "create" | "edit";
  initialValues?: Agent;
  modelConfigs: ModelConfig[];
  onCancel: () => void;
  onSubmitted: () => void;
};

export function AgentFormModal({
  open,
  mode,
  initialValues,
  modelConfigs,
  onCancel,
  onSubmitted,
}: AgentFormModalProps) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const memoryPolicy = Form.useWatch("memory_policy", form);
  const toolChoice = Form.useWatch("tool_choice", form);

  // Reset the form whenever the modal opens. Edit mode pre-fills from
  // initialValues; create mode uses the project defaults. Done in an
  // effect on `open` so the form is clean on every open. resetFields
  // clears any leftover values from a previous open (defensive even
  // with destroyOnClose, in case the form instance is reused).
  useEffect(() => {
    if (!open) return;
    form.resetFields();
    if (mode === "edit" && initialValues) {
      form.setFieldsValue({
        name: initialValues.name,
        description: initialValues.description ?? undefined,
        prompt_template: initialValues.prompt_template,
        model_name: initialValues.model_name,
        temperature: initialValues.temperature,
        memory_policy: initialValues.memory_policy ?? "sliding_window",
        memory_window_size: initialValues.memory_window_size ?? 20,
        memory_max_tokens: initialValues.memory_max_tokens ?? 4000,
        memory_compression: initialValues.memory_compression ?? false,
        tool_choice: initialValues.tool_choice ?? "auto",
        tool_choice_required: initialValues.tool_choice_required ?? false,
        allowed_tools: initialValues.allowed_tools ?? [],
        // M21: prefill KB bindings (response uses knowledge_bases: KBRef[],
        // form uses knowledge_base_ids: number[])
        knowledge_base_ids: initialValues.knowledge_bases?.map((kb) => kb.id) ?? [],
        kb_retrieval_config: initialValues.kb_retrieval_config ?? { top_k: 3, rrf_k: 30 },
      });
    } else {
      form.setFieldsValue(DEFAULT_VALUES);
    }
  }, [open, mode, initialValues, form]);

  const handleFinish = async (values: AgentCreatePayload) => {
    setSubmitting(true);
    try {
      if (mode === "create") {
        const payload: AgentCreatePayload = { ...DEFAULT_VALUES, ...values };
        const res = await agentApi.create(payload);
        if (res.data.code === 200) {
          message.success("创建成功");
          onSubmitted();
        } else {
          message.error("创建失败");
        }
      } else if (initialValues) {
        const res = await agentApi.update(initialValues.id, values);
        if (res.data.code === 200) {
          message.success("保存成功");
          onSubmitted();
        } else {
          message.error("保存失败");
        }
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || "操作失败";
      message.error(detail);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title={mode === "create" ? "创建Agent" : "编辑Agent"}
      open={open}
      // Disable the X / mask-click close while a request is in flight so
      // the user can't dismiss the modal mid-submit (spec 3.4).
      onCancel={submitting ? undefined : onCancel}
      closable={!submitting}
      maskClosable={!submitting}
      footer={null}
      width={680}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onFinish={handleFinish}>
        <Form.Item
          name="name"
          label="名称"
          rules={[{ required: true, message: "请输入名称" }]}
        >
          <Input placeholder="请输入Agent名称" />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea placeholder="请输入描述" />
        </Form.Item>
        <Form.Item
          name="prompt_template"
          label="提示词模板"
          rules={[{ required: true, message: "请输入提示词模板" }]}
        >
          <TextArea rows={4} placeholder="请输入提示词模板，使用 {'{input}'} 表示用户输入" />
        </Form.Item>
        <Form.Item
          name="model_name"
          label="模型"
          rules={[{ required: true, message: "请选择模型" }]}
        >
          <Select placeholder="请选择模型" showSearch optionFilterProp="children">
            {modelConfigs.map((model) => (
              <Select.Option key={model.id} value={model.model_name}>
                {model.name} ({model.model_type} - {model.model_name})
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item name="temperature" label="温度">
          <Select>
            <Select.Option value={0}>精确 (0)</Select.Option>
            <Select.Option value={0.7}>平衡 (0.7)</Select.Option>
            <Select.Option value={1}>创意 (1)</Select.Option>
          </Select>
        </Form.Item>

        <Divider plain style={{ margin: "8px 0 16px" }}>
          记忆策略 (Memory Policy)
        </Divider>
        <Form.Item name="memory_policy" label="策略">
          <Select>
            {MEMORY_POLICIES.map((p) => (
              <Select.Option key={p.value} value={p.value}>
                {p.label}
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        {(memoryPolicy === "sliding_window" || memoryPolicy === "semantic_compression") && (
          <Form.Item
            name="memory_window_size"
            label="窗口大小 (轮)"
            tooltip="保留最近 N 条消息"
          >
            <InputNumber min={1} max={200} style={{ width: "100%" }} />
          </Form.Item>
        )}
        {memoryPolicy === "token_limit" && (
          <Form.Item
            name="memory_max_tokens"
            label="最大 Token 数"
            tooltip="历史消息总 token 超过此值时丢弃最早的消息"
          >
            <InputNumber min={100} max={32000} step={100} style={{ width: "100%" }} />
          </Form.Item>
        )}
        {memoryPolicy === "semantic_compression" && (
          <Form.Item
            name="memory_compression"
            label="启用语义压缩"
            valuePropName="checked"
            tooltip="对较早的历史消息进行摘要压缩 (需要可用的 chat 模型)"
          >
            <Switch />
          </Form.Item>
        )}

        <Divider plain style={{ margin: "8px 0 16px" }}>
          工具策略 (Tool Choice)
        </Divider>
        <Form.Item name="tool_choice" label="工具调用方式">
          <Select>
            {TOOL_CHOICE_MODES.map((m) => (
              <Select.Option key={m.value} value={m.value}>
                {m.label}
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        {toolChoice === "required" && (
          <Form.Item
            name="tool_choice_required"
            label="强制调用"
            valuePropName="checked"
            tooltip="要求 LLM 每次都至少调用一个工具"
          >
            <Switch />
          </Form.Item>
        )}
        {toolChoice === "specific" && (
          <Form.Item
            name="allowed_tools"
            label="允许的工具"
            tooltip="从 Agent 已配置的工具中挑选；输入工具名后回车确认"
          >
            <Select mode="tags" tokenSeparators={[",", " "]} placeholder="输入工具名后回车" />
          </Form.Item>
        )}

        <Divider plain style={{ margin: "8px 0 16px" }}>
          知识库 (Knowledge Base)
        </Divider>
        <Form.Item
          name="knowledge_base_ids"
          label="绑定的知识库"
          tooltip="Agent 会在 chat 时自动从已选 KB 检索相关内容,辅助回答"
        >
          <MultiKBSelector />
        </Form.Item>
        <Form.Item
          name="kb_retrieval_config"
          label="检索设置"
          tooltip="top_k = 每 KB 召回 chunk 数;rrf_k = RRF 融合常数"
        >
          <KbRetrievalConfigFields />
        </Form.Item>

        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={submitting}>
              {mode === "create" ? "创建" : "保存"}
            </Button>
            <Button onClick={onCancel} disabled={submitting}>
              取消
            </Button>
          </Space>
        </Form.Item>
      </Form>
    </Modal>
  );
}
