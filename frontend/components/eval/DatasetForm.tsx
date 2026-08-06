"use client";

// frontend/components/eval/DatasetForm.tsx
// M37.1 — "新建 / 编辑 dataset" modal。
//
// 表单字段:
//   - KB 下拉:必填,从 /api/v1/knowledge/ 取当前租户可见的 KB
//   - name:必填,1-200 字符(Pydantic EvalDatasetCreate.name 校验)
//   - description:可选,0-2000 字符
//   - source:可选 Literal(manual / imported / synthetic),默认 manual
//
// 编辑模式(M37.1 暂未在 UI 上暴露编辑,先留接口给后续 support)走 EditForm 字段集
// —— 只读 name / description / is_active,kb_id 不可改(后端 EvalDatasetUpdate 也禁了)。

import { useEffect } from "react";
import {
  Modal,
  Form,
  Input,
  Select,
} from "antd";
import { useQuery } from "@tanstack/react-query";
import { knowledgeApi } from "@/services/knowledge";
import type {
  EvalDatasetCreate,
  EvalDatasetSource,
} from "@/types/eval_dataset";

const { TextArea } = Input;

interface DatasetFormProps {
  open: boolean;
  onCancel: () => void;
  onSubmit: (payload: EvalDatasetCreate) => Promise<void> | void;
  // 编辑模式时传入(本组件 T5 暂不启用 edit 入口,留接口)
  initial?: Partial<EvalDatasetCreate>;
  // 提交按钮 loading 状态(由父组件 useMutation 控制)
  submitting?: boolean;
}

const SOURCE_OPTIONS: { value: EvalDatasetSource; label: string }[] = [
  { value: "manual", label: "手动创建" },
  { value: "imported", label: "导入" },
  { value: "synthetic", label: "合成生成" },
];

export default function DatasetForm({
  open,
  onCancel,
  onSubmit,
  initial,
  submitting,
}: DatasetFormProps) {
  const [form] = Form.useForm<EvalDatasetCreate>();

  // 拉 KB 列表(用于下拉)。M37.1 不要求 KB 单选过滤,take all visible
  const { data: kbData } = useQuery({
    queryKey: ["knowledge", "list-for-eval-form"],
    queryFn: () => knowledgeApi.list(1, 100),
    enabled: open,
  });

  // 每次打开 modal 重置表单到 initial
  useEffect(() => {
    if (open) {
      form.resetFields();
      if (initial) {
        form.setFieldsValue(initial);
      } else {
        // 新建默认 source=manual
        form.setFieldsValue({ source: "manual" });
      }
    }
  }, [open, initial, form]);

  return (
    <Modal
      title={initial ? "编辑评测集" : "新建评测集"}
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
          // antd Form 校验失败会自己显示红字,这里吞掉
        }
      }}
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item
          label="所属知识库"
          name="kb_id"
          rules={[{ required: true, message: "请选择知识库" }]}
        >
          <Select
            placeholder="选择一个知识库(dataset 内的 query 都会从这个 KB 检索)"
            showSearch
            optionFilterProp="label"
            options={((kbData?.data as any) ?? []).map((kb: { id: number; name: string }) => ({
              value: kb.id,
              label: kb.name,
            }))}
          />
        </Form.Item>
        <Form.Item
          label="名称"
          name="name"
          rules={[
            { required: true, message: "请输入名称" },
            { max: 200, message: "最多 200 字符" },
          ]}
        >
          <Input placeholder="例如:产品 FAQ 基线 / 合同抽取难点" />
        </Form.Item>
        <Form.Item
          label="描述"
          name="description"
          rules={[{ max: 2000, message: "最多 2000 字符" }]}
        >
          <TextArea
            rows={3}
            placeholder="可选,描述这个评测集的目的 / 来源 / 维护者"
          />
        </Form.Item>
        <Form.Item label="来源" name="source">
          <Select options={SOURCE_OPTIONS} />
        </Form.Item>
      </Form>
    </Modal>
  );
}