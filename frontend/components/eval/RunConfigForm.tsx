"use client";

// frontend/components/eval/RunConfigForm.tsx
// M37.2 — "启动评测" modal 表单。
//
// 表单字段:
//   - name:可选 run 别名
//   - top_k:1-100,默认 10
//   - rerank:checkbox,默认 true
//   - search_weights:4 维 slider/title / important_kw / question_kw / text
//     —— 用数字 InputNumber 简化(项目 convention tts/playbook 也有相同 pattern)
//   - embedding_model_config_id / judge_model_config_id:
//     必填,从 /api/v1/models/ 拉的 chat/embedding 模型下拉
//   - judge_metrics:多选[faithfulness / answer_relevancy]
//
// 提交后调 ``startRun({ dataset_id, config })`` 触发评测(Celery eager 模式同步跑完),
// 父组件拿 run_id 做后续跳详情 / 轮询。

import { useEffect } from "react";
import {
  Modal,
  Form,
  Input,
  InputNumber,
  Checkbox,
  Select,
  Space,
} from "antd";
import { useQuery } from "@tanstack/react-query";
import type { EvalRunConfig } from "@/types/eval_run";

interface RunConfigFormProps {
  open: boolean;
  onCancel: () => void;
  onSubmit: (payload: EvalRunConfig) => Promise<void> | void;
  /** KB 绑定的 embedding model — 锁定表单默认值,不允许改 */
  defaultEmbeddingModelConfigId: number;
  submitting?: boolean;
}

const DEFAULT_SEARCH_WEIGHTS: Record<string, number> = {
  title: 10,
  important_kw: 30,
  question_kw: 20,
  text: 2,
};

const JUDGE_METRIC_OPTIONS = [
  { value: "faithfulness", label: "Faithfulness(0/1/2)" },
  { value: "answer_relevancy", label: "Answer Relevancy(0/1/2)" },
];

interface ModelOption {
  id: number;
  name: string;
  is_chat: number;
  is_embedding: number;
  is_default: number;
}

export default function RunConfigForm({
  open,
  onCancel,
  onSubmit,
  defaultEmbeddingModelConfigId,
  submitting,
}: RunConfigFormProps) {
  const [form] = Form.useForm<EvalRunConfig>();

  // 拉模型列表(用于 judge model 下拉;embedding 用 KB 锁定的值,不允许改)
  const { data: modelData } = useQuery({
    queryKey: ["models", "list-for-eval-form"],
    queryFn: async () => {
      const res = await fetch(
        "/api/v1/models/?is_active=1&is_chat=1&page=1&page_size=100",
        {
          headers: {
            Authorization: `Bearer ${localStorage.getItem("access_token") ?? ""}`,
          },
        },
      );
      if (!res.ok) return { items: [] as ModelOption[] };
      const body = await res.json();
      return { items: (body.data ?? []) as ModelOption[] };
    },
    enabled: open,
  });

  // 每次打开 modal 重置表单
  useEffect(() => {
    if (open) {
      form.resetFields();
      form.setFieldsValue({
        search_weights: { ...DEFAULT_SEARCH_WEIGHTS },
        top_k: 10,
        rerank: true,
        rerank_top_n: 5,
        embedding_model_config_id: defaultEmbeddingModelConfigId,
        judge_metrics: ["faithfulness", "answer_relevancy"],
      });
    }
  }, [open, defaultEmbeddingModelConfigId, form]);

  const chatModels = (modelData?.items ?? []).filter(
    (m) => m.is_chat === 1,
  );

  return (
    <Modal
      title="启动评测"
      open={open}
      onCancel={onCancel}
      okText="启动"
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnClose
      width={560}
      onOk={async () => {
        try {
          const values = await form.validateFields();
          await onSubmit(values);
        } catch {
          // antd Form 校验失败会自己显示红字,这里吞掉
        }
      }}
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item label="Run 别名" name="name">
          <Input placeholder="可选,例如:baseline / rerank-on" />
        </Form.Item>

        <Form.Item
          label="Top-K"
          name="top_k"
          rules={[{ required: true, message: "请输入 Top-K" }]}
        >
          <InputNumber min={1} max={100} style={{ width: "100%" }} />
        </Form.Item>

        <Form.Item label="开启 Rerank" name="rerank" valuePropName="checked">
          <Checkbox>Rerank 提升 top 结果质量</Checkbox>
        </Form.Item>

        <Form.Item label="检索权重(search_weights)" required>
          <Space.Compact block>
            {(["title", "important_kw", "question_kw", "text"] as const).map(
              (k) => (
                <Form.Item
                  key={k}
                  name={["search_weights", k]}
                  noStyle
                  rules={[{ required: true, message: `${k} 必填` }]}
                >
                  <InputNumber
                    min={0}
                    max={100}
                    step={1}
                    addonBefore={k}
                    style={{ width: 160 }}
                    placeholder={String(DEFAULT_SEARCH_WEIGHTS[k])}
                  />
                </Form.Item>
              ),
            )}
          </Space.Compact>
        </Form.Item>

        <Form.Item
          label="Embedding 模型(KB 锁定)"
          name="embedding_model_config_id"
          rules={[{ required: true, message: "请确认 embedding 模型" }]}
        >
          <InputNumber min={1} style={{ width: "100%" }} disabled />
        </Form.Item>

        <Form.Item
          label="Judge 模型"
          name="judge_model_config_id"
          rules={[{ required: true, message: "请选 judge 模型" }]}
        >
          <Select
            placeholder="选一个 chat 模型当 judge"
            showSearch
            optionFilterProp="label"
            options={chatModels.map((m) => ({
              value: m.id,
              label: `${m.name}${m.is_default ? " (default)" : ""}`,
            }))}
          />
        </Form.Item>

        <Form.Item label="Judge 指标" name="judge_metrics">
          <Select
            mode="multiple"
            options={JUDGE_METRIC_OPTIONS}
            placeholder="默认两项都跑"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
