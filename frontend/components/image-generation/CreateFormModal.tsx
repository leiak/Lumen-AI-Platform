// frontend/components/image-generation/CreateFormModal.tsx
// M22 — image generation feature (T17)
//
// Spec: docs/superpowers/specs/2026-06-11-image-generation-design.md §5.2
//
// Modal that posts a new image generation request. The task is async on the
// backend (status goes `pending → generating → completed/failed`) so we only
// show a "task submitted" toast here and let the notifications stream
// (M12 /ws/web) tell the user when the image is ready.
"use client";

import { useEffect, useState } from "react";
import { Modal, Form, Input, Select, InputNumber, Button, App } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { imageGenerationApi } from "@/services/image-generation";
import { modelsApi, type ModelConfig } from "@/services/models";
import PlaybookSelect from "@/components/PlaybookSelect";

const { TextArea } = Input;

export interface CreateFormModalProps {
  open: boolean;
  onClose: () => void;
}

export function CreateFormModal({ open, onClose }: CreateFormModalProps) {
  const [form] = Form.useForm();
  const { message } = App.useApp();
  const qc = useQueryClient();
  // Track the selected model's `model_type` so we can show the OpenAI-only
  // `quality` / `style` dropdowns (DALL-E 3) without leaking them into the
  // payload for non-OpenAI backends.
  const [modelType, setModelType] = useState<string>("");

  // Pull only image-capable, active models. The list endpoint returns a
  // PaginatedResponse envelope, so we unwrap `res.data.data` here (same
  // pattern as EmbeddingModelSelect).
  const { data: models } = useQuery({
    queryKey: ["models", "image-generation"],
    queryFn: async (): Promise<ModelConfig[]> => {
      const res = await modelsApi.list(1, 100, { is_image_generation: true, is_active: true });
      if (res.data?.code === 200) {
        return (res.data.data ?? []) as ModelConfig[];
      }
      return [];
    },
    enabled: open,
  });

  const createMut = useMutation({
    mutationFn: (values: any) => imageGenerationApi.create(values),
    onSuccess: () => {
      message.success("已提交生成任务,完成后会通过通知告知");
      qc.invalidateQueries({ queryKey: ["image-generation"] });
      form.resetFields();
      setModelType("");
      onClose();
    },
    onError: (e: Error) => message.error(e.message),
  });

  // Reset the form whenever the modal closes so reopening starts fresh.
  // `destroyOnClose` on the Modal already unmounts the form, but
  // resetFields() is a defensive belt-and-braces — if the form instance
  // is ever reused (e.g. parent lifts it), this guarantees no stale
  // values sneak in.
  useEffect(() => {
    if (!open) form.resetFields();
  }, [open, form]);

  return (
    <Modal
      open={open}
      title="新建图片生成"
      onCancel={onClose}
      footer={null}
      width={640}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={(v) => createMut.mutate(v)}
        initialValues={{ size: "1024x1024", n: 1 }}
      >
        <Form.Item
          name="model_config_id"
          label="模型"
          rules={[{ required: true, message: "请选择图片生成模型" }]}
        >
          <Select
            placeholder="请选择模型"
            showSearch
            optionFilterProp="label"
            onChange={(v) => {
              const m: ModelConfig | undefined = models?.find((x) => x.id === v);
              setModelType(m?.model_type || "");
            }}
            options={(models || []).map((m) => ({
              value: m.id,
              label: `${m.name} (${m.model_type})`,
            }))}
          />
        </Form.Item>
        <Form.Item
          name="prompt"
          label="Prompt"
          rules={[{ required: true, max: 4000 }]}
        >
          <TextArea rows={4} maxLength={4000} showCount placeholder="描述你想生成的图片..." />
        </Form.Item>
        {/* M35: optional Playbook — when set, backend enriches the prompt
            with style keywords (palette / typography / avoid) before calling
            the provider. Built-ins like "clean-professional" inject cool-blue
            palette hints → images lean cooler. See playbook_service.py
            `inject_into_prompt()`. */}
        <Form.Item name="playbook_id" label="Playbook (可选)">
          <PlaybookSelect scope="image" placeholder="选择 Playbook 自动注入风格关键词" />
        </Form.Item>
        <Form.Item name="negative_prompt" label="负向 Prompt (可选)">
          <TextArea rows={2} maxLength={4000} placeholder="不想出现的内容..." />
        </Form.Item>
        <Form.Item name="size" label="尺寸">
          <Select
            options={[
              { value: "512x512", label: "512 × 512" },
              { value: "1024x1024", label: "1024 × 1024" },
              { value: "1024x1792", label: "1024 × 1792" },
              { value: "1792x1024", label: "1792 × 1024" },
            ]}
          />
        </Form.Item>
        <Form.Item name="n" label="数量">
          <InputNumber min={1} max={4} />
        </Form.Item>
        {modelType === "openai" && (
          <>
            <Form.Item name="quality" label="质量">
              <Select
                allowClear
                options={[
                  { value: "standard", label: "standard" },
                  { value: "hd", label: "hd" },
                ]}
              />
            </Form.Item>
            <Form.Item name="style" label="风格">
              <Select
                allowClear
                options={[
                  { value: "vivid", label: "vivid" },
                  { value: "natural", label: "natural" },
                ]}
              />
            </Form.Item>
          </>
        )}
        <Form.Item name="extra_params" label="extra_params JSON (可选, 高级)">
          <TextArea rows={3} placeholder='{"seed": 42, "guidance_scale": 7.5}' />
        </Form.Item>
        <div style={{ textAlign: "right" }}>
          <Button onClick={onClose} style={{ marginRight: 8 }}>取消</Button>
          <Button type="primary" htmlType="submit" loading={createMut.isPending}>
            提交生成
          </Button>
        </div>
      </Form>
    </Modal>
  );
}
