"use client";
import { Form, Input, Modal, Select, Switch } from "antd";
import { useState } from "react";
import { MarketplaceSkill, skillAdminApi } from "@/services/skills";
import { App } from "antd";
import {
  PromptFields, ScriptFields, HttpFields, KBFields, MCPFields,
} from "./FieldSubcomponents";

const TYPE_OPTIONS = [
  { value: "prompt", label: "提示词" },
  { value: "script", label: "脚本" },
  { value: "http", label: "API" },
  { value: "knowledge_retrieval", label: "知识库" },
  { value: "tool", label: "工具 (MCP)" },
];

export function SkillUpsertForm({
  skill,
  onSave,
  onCancel,
}: {
  skill?: MarketplaceSkill | null;
  onSave: () => void;
  onCancel: () => void;
}) {
  const { message } = App.useApp();
  const [type, setType] = useState<string>(skill?.type ?? "prompt");
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);

  const initialValues = skill
    ? {
        name: skill.name,
        category: skill.category,
        type: skill.type,
        description: skill.description,
        content: skill.content,
        type_config: skill.type_config ?? {},
        version: skill.version,
        provider: skill.provider,
        is_verified: skill.is_verified,
      }
    : { type: "prompt", version: "1.0.0", category: "code", is_verified: false };

  const handleSubmit = async () => {
    const values = await form.validateFields();
    setSubmitting(true);
    try {
      const payload = {
        ...values,
        content: values.type === "prompt" ? values.content : undefined,
        type_config: values.type === "prompt" ? undefined : values.type_config,
      };
      const url = skill
        ? `/api/v1/admin/skills/${skill.id}`
        : "/api/v1/admin/skills/";
      const method = skill ? "PUT" : "POST";
      const r = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => null);
        throw new Error(j?.detail || `HTTP ${r.status}`);
      }
      message.success(skill ? "更新成功" : "创建成功");
      onSave();
    } catch (e) {
      message.error(`保存失败: ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title={skill ? `编辑技能 — ${skill.name}` : "新建技能"}
      open
      onCancel={onCancel}
      onOk={handleSubmit}
      confirmLoading={submitting}
      okText="保存"
      cancelText="取消"
      width={700}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" initialValues={initialValues}>
        <Form.Item name="name" label="名称" rules={[{ required: true, max: 100 }]}>
          <Input placeholder="技能名称" />
        </Form.Item>
        <Form.Item name="category" label="分类" rules={[{ required: true }]}>
          <Input placeholder="code / writing / data / testing / design" />
        </Form.Item>
        <Form.Item name="type" label="类型" rules={[{ required: true }]}>
          <Select
            options={TYPE_OPTIONS}
            onChange={setType}
            disabled={!!skill}
          />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={2} />
        </Form.Item>
        {type === "prompt" && <PromptFields />}
        {type === "script" && <ScriptFields />}
        {type === "http" && <HttpFields />}
        {type === "knowledge_retrieval" && <KBFields />}
        {type === "tool" && <MCPFields />}
        <Form.Item name="version" label="版本" rules={[{ required: true }]}>
          <Input placeholder="1.0.0" />
        </Form.Item>
        <Form.Item name="is_verified" label="已认证" valuePropName="checked">
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  );
}
