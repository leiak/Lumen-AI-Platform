"use client";

import { useEffect } from "react";
import { Modal, Form, Input, Select, message } from "antd";
import { modelsApi, ModelConfig } from "@/services/models";

export interface CreateModelInlineModalProps {
  open: boolean;
  initialModelName?: string;
  onCancel: () => void;
  onCreated: (created: ModelConfig) => void;
}

const PROVIDER_OPTIONS = [
  { value: "ollama", label: "Ollama (本地)" },
  { value: "anthropic", label: "Anthropic" },
  { value: "zhipu", label: "智谱 GLM" },
  { value: "minimax", label: "MiniMax" },
];

interface FormValues {
  name: string;
  model_type: string;
  model_name: string;
  base_url: string;
  api_key: string;
}

export function CreateModelInlineModal({
  open,
  initialModelName = "",
  onCancel,
  onCreated,
}: CreateModelInlineModalProps) {
  const [form] = Form.useForm<FormValues>();

  useEffect(() => {
    if (open) {
      // Pre-fill model_name with the search term; leave provider blank
      // (user must pick explicitly).
      form.setFieldsValue({
        name: initialModelName,
        model_name: initialModelName,
        model_type: undefined,
        base_url: "",
        api_key: "",
      });
    }
  }, [open, initialModelName, form]);

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      const response = await modelsApi.create(values);
      if (response.data.code === 200) {
        if (!response.data.data) {
          message.error("创建失败: 服务端未返回模型配置");
          return;
        }
        message.success("模型已创建");
        onCreated(response.data.data);
      } else {
        message.error(`创建失败: ${response.data.message ?? "未知错误"}`);
      }
    } catch (err: any) {
      if (err?.errorFields) {
        // AntD form validation error — already shown inline.
        return;
      }
      message.error(`创建失败: ${err?.message ?? "未知错误"}`);
    }
  };

  return (
    <Modal
      title="新建模型配置"
      open={open}
      onOk={handleOk}
      onCancel={onCancel}
      okText="创建"
      cancelText="取消"
      destroyOnHidden
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item
          name="name"
          label="配置名称"
          rules={[{ required: true, message: "请填写配置名称" }]}
        >
          <Input placeholder="例如:智谱 GLM-4 生产" />
        </Form.Item>
        <Form.Item
          name="model_type"
          label="Provider"
          rules={[{ required: true, message: "请选择 Provider" }]}
        >
          <Select placeholder="选择 Provider" options={PROVIDER_OPTIONS} />
        </Form.Item>
        <Form.Item
          name="model_name"
          label="模型名称"
          rules={[{ required: true, message: "请填写模型名称" }]}
        >
          <Input placeholder="例如:glm-4" />
        </Form.Item>
        <Form.Item
          name="base_url"
          label="Base URL"
          tooltip="Ollama 可留空"
        >
          <Input placeholder="例如:https://api.zhipu.example" />
        </Form.Item>
        <Form.Item
          name="api_key"
          label="API Key"
          tooltip="Ollama 可留空"
        >
          <Input.Password placeholder="API Key" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

export default CreateModelInlineModal;
