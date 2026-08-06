"use client";

// frontend/components/eval/ItemFormModal.tsx
// M37.1 — "新增 / 编辑 item" modal。
//
// 表单字段:
//   - query:必填
//   - expected_doc_ids:Tags 数组(用户逐个输入数字 → 回车添加 tag)
//   - expected_answer:可选 TextArea
//   - answer_keywords:Tags 数组(字符串 tag)
//   - category:Select(5 选 1)
//   - difficulty:Select(3 选 1),默认 medium
//   - notes:可选 TextArea
//
// M37.1 后端只有 add_item,没有 update item endpoint(T6 spec 注)。本组件
// 先只走 add_item;编辑模式留接口给未来 patch_item 实现。

import { useEffect } from "react";
import { Modal, Form, Input, Select } from "antd";
import type {
  EvalDatasetCategory,
  EvalDatasetDifficulty,
  EvalDatasetItem,
  EvalDatasetItemCreate,
} from "@/types/eval_dataset";

const { TextArea } = Input;

interface ItemFormModalProps {
  open: boolean;
  onCancel: () => void;
  onSubmit: (payload: EvalDatasetItemCreate) => Promise<void> | void;
  // 编辑模式(暂未启用,留接口)
  initial?: EvalDatasetItem;
  submitting?: boolean;
}

const CATEGORY_OPTIONS: { value: EvalDatasetCategory; label: string }[] = [
  { value: "factual", label: "事实" },
  { value: "reasoning", label: "推理" },
  { value: "multi_hop", label: "多跳" },
  { value: "keyword_heavy", label: "关键词" },
  { value: "out_of_scope", label: "越界" },
];

const DIFFICULTY_OPTIONS: { value: EvalDatasetDifficulty; label: string }[] = [
  { value: "easy", label: "简单" },
  { value: "medium", label: "中等" },
  { value: "hard", label: "困难" },
];

export default function ItemFormModal({
  open,
  onCancel,
  onSubmit,
  initial,
  submitting,
}: ItemFormModalProps) {
  const [form] = Form.useForm<EvalDatasetItemCreate>();

  useEffect(() => {
    if (open) {
      form.resetFields();
      if (initial) {
        form.setFieldsValue({
          query: initial.query,
          expected_doc_ids: initial.expected_doc_ids ?? [],
          expected_answer: initial.expected_answer ?? undefined,
          answer_keywords: initial.answer_keywords ?? [],
          category: initial.category ?? undefined,
          difficulty: initial.difficulty ?? "medium",
          notes: initial.notes ?? undefined,
        });
      } else {
        form.setFieldsValue({ difficulty: "medium" });
      }
    }
  }, [open, initial, form]);

  return (
    <Modal
      title={initial ? "编辑 item" : "新增 item"}
      open={open}
      onCancel={onCancel}
      okText="保存"
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnClose
      onOk={async () => {
        try {
          const values = await form.validateFields();
          await onSubmit(values);
        } catch {
          // antd Form 校验失败自己展示
        }
      }}
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item
          label="Query"
          name="query"
          rules={[{ required: true, message: "请输入 query" }]}
        >
          <Input placeholder="例如:如何申请退货?" />
        </Form.Item>

        <Form.Item
          label="期望文档 ID"
          name="expected_doc_ids"
          tooltip="回车逐个添加 document id;评测时检索命中的 docs 必须包含这些 id 才算 recall@1 命中。"
        >
          <Select mode="tags" placeholder="输入数字回车" tokenSeparators={[","]} />
        </Form.Item>

        <Form.Item label="期望答案(可选)" name="expected_answer">
          <TextArea rows={3} placeholder="可填标准答案;answer-quality 指标会做关键词 / 长度匹配。" />
        </Form.Item>

        <Form.Item label="答案关键词(可选)" name="answer_keywords">
          <Select
            mode="tags"
            placeholder="输入关键词回车(用于 keyword_heavy 类别的精确匹配)"
            tokenSeparators={[","]}
          />
        </Form.Item>

        <Form.Item label="分类" name="category">
          <Select
            allowClear
            options={CATEGORY_OPTIONS}
            placeholder="选择查询类型(用于分桶统计)"
          />
        </Form.Item>

        <Form.Item label="难度" name="difficulty">
          <Select options={DIFFICULTY_OPTIONS} />
        </Form.Item>

        <Form.Item label="备注(可选)" name="notes">
          <TextArea rows={2} placeholder="维护者备注 / 内部标签" />
        </Form.Item>
      </Form>
    </Modal>
  );
}