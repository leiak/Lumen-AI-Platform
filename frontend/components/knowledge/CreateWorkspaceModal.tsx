"use client";

// M38.2: 新建 workspace 的轻量表单 —— name + description + icon + color。

import { useEffect } from "react";
import { Modal, Form, Input, ColorPicker, Select } from "antd";
import type { WorkspaceCreatePayload } from "@/types/workspace";

const { TextArea } = Input;

const PRESET_ICONS = [
  { value: "📁", label: "📁" },
  { value: "📚", label: "📚" },
  { value: "🔬", label: "🔬" },
  { value: "💼", label: "💼" },
  { value: "🛠️", label: "🛠️" },
  { value: "🎨", label: "🎨" },
];

const PRESET_COLORS = [
  "#1890ff",
  "#52c41a",
  "#faad14",
  "#f5222d",
  "#722ed1",
  "#13c2c2",
];

export interface CreateWorkspaceModalProps {
  open: boolean;
  onCancel: () => void;
  onSubmit: (payload: WorkspaceCreatePayload) => Promise<void> | void;
}

export default function CreateWorkspaceModal(
  props: CreateWorkspaceModalProps
) {
  const { open, onCancel, onSubmit } = props;
  const [form] = Form.useForm<WorkspaceCreatePayload>();

  useEffect(() => {
    if (open) form.resetFields();
  }, [open, form]);

  return (
    <Modal
      title="新建 workspace"
      open={open}
      onCancel={onCancel}
      onOk={async () => {
        const values = await form.validateFields();
        // ColorPicker 给的是 Color 对象,统一成 hex 字符串。
        // 用 any cast 兜底 — AntD Color 类型复杂,在 strict mode 下会触发
        // `Property 'toHexString' does not exist on type 'never'`,因为 AntD
        // form 的 narrow 把这个分支的 color 推断成了 never。
        const rawColor = values.color as unknown;
        const colorValue =
          typeof rawColor === "string"
            ? rawColor
            : (rawColor as { toHexString?: () => string; toRgbString?: () => string })?.toHexString?.() ??
              (rawColor as { toRgbString?: () => string })?.toRgbString?.() ??
              String(rawColor ?? "");
        await onSubmit({ ...values, color: colorValue });
      }}
      okText="创建"
      cancelText="取消"
      destroyOnClose
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item
          name="name"
          label="名称"
          rules={[{ required: true, message: "请输入 workspace 名" }]}
        >
          <Input placeholder="例如:研发 / 产品 / 客户支持" maxLength={100} />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <TextArea
            rows={3}
            placeholder="可选,描述 workspace 的用途"
            maxLength={500}
          />
        </Form.Item>
        <Form.Item name="icon" label="图标" initialValue="📁">
          <Select
            options={PRESET_ICONS.map((i) => ({ value: i.value, label: i.label }))}
          />
        </Form.Item>
        <Form.Item name="color" label="颜色" initialValue="#1890ff">
          <ColorPicker
            presets={[
              {
                label: "预设",
                colors: PRESET_COLORS,
              },
            ]}
            showText
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}