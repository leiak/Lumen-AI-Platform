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
import EmbeddingModelSelect from "@/components/EmbeddingModelSelect";
import type { EvalRunConfig } from "@/types/eval_run";

interface RunConfigFormProps {
  open: boolean;
  onCancel: () => void;
  onSubmit: (payload: EvalRunConfig) => Promise<void> | void;
  /**
   * KB 绑定的 embedding model — 锁定表单默认值,不允许改。
   * 父组件等 KB 详情 query 返回后才传,中间态为 undefined。
   */
  defaultEmbeddingModelConfigId?: number;
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
  // 后端 ModelConfigResponse 里这几个字段都是 bool,Pydantic 序列化成 JSON
  // true/false。前版写成 number + `=== 1` 是 pre-existing 类型不匹配 bug,
  // 导致 Judge 下拉被 filter 完永远是空数组。
  is_chat: boolean;
  is_embedding: boolean;
  is_default: boolean;
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
  //
  // 走**绝对 URL**直接连后端(localhost:11335),不走 Next.js rewrites。
  // 走 Next.js 代理 (`/api/v1/...`) 时碰到 308 trailing-slash 重定向,
  // 跨 port redirect 会把 Authorization header 剥掉,最终到后端 401,
  // res.ok=false → 返回空数组 → Judge 下拉永远是空。
  // pre-existing bug,M37.2 修。还有几个 page 也有同样写法但本次不夹。
  const { data: modelData } = useQuery({
    queryKey: ["models", "list-for-eval-form"],
    queryFn: async () => {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:11335/api/v1"}/models/?is_active=1&is_chat=1&page=1&page_size=100`,
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

  // 每次打开 modal 重置表单 —— 只看 open,不看 defaultEmbeddingModelConfigId。
  // KB 详情 query 比 models 慢一点,开门瞬间默认 embedding_id 还在路上;
  // 若把它放进 deps,后续 KB 返回时会再次 resetFields 把用户已经填的
  // top_k / judge 抹掉,所以拆出第二个 effect 单独推 embedding 字段。
  useEffect(() => {
    if (open) {
      form.resetFields();
      form.setFieldsValue({
        search_weights: { ...DEFAULT_SEARCH_WEIGHTS },
        top_k: 10,
        rerank: true,
        rerank_top_n: 5,
        judge_metrics: ["faithfulness", "answer_relevancy"],
      });
    }
  }, [open, form]);

  // KB 加载完后单独更新 embedding 字段,不影响用户已填值
  useEffect(() => {
    if (open && defaultEmbeddingModelConfigId !== undefined) {
      form.setFieldValue(
        "embedding_model_config_id",
        defaultEmbeddingModelConfigId,
      );
    }
  }, [defaultEmbeddingModelConfigId, open, form]);

  const chatModels = (modelData?.items ?? []).filter(
    (m) => m.is_chat === true,
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
          // 展示用人能读的名字(model_name · model_type),而不是一个数字 ID。
          // EmbeddingModelSelect disabled 模式自带 "创建后不可更改" 提示。
          tooltip="由关联 KB 决定 — 后端在 EvalRunCreate 时强校验必须等于 KB 的 embedding model,改也 500"
        >
          <EmbeddingModelSelect disabled />
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
