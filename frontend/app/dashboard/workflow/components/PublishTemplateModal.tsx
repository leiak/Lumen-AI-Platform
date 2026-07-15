"use client";

import { Modal, Form, Input, Space, Button } from "antd";
import { useEffect } from "react";

interface InitialValues {
  name: string;
  description?: string;
}

interface Props {
  open: boolean;
  submitting: boolean;
  initialValues: InitialValues;
  onCancel: () => void;
  onSubmit: (values: {
    name: string;
    description?: string;
    category?: string;
  }) => Promise<boolean>;
}

/**
 * M30b: "publish as template" modal. The parent pre-fills name /
 * description by fetching the source workflow; the user can edit
 * the values before submitting.
 */
export function PublishTemplateModal({
  open,
  submitting,
  initialValues,
  onCancel,
  onSubmit,
}: Props) {
  const [form] = Form.useForm();

  useEffect(() => {
    if (open) {
      form.setFieldsValue({
        name: initialValues.name,
        description: initialValues.description || "",
        category: "general",
      });
    } else {
      form.resetFields();
    }
  }, [open, initialValues, form]);

  return (
    <Modal
      title="发布为模板"
      open={open}
      onCancel={onCancel}
      footer={null}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={async (values) => {
          const ok = await onSubmit(values);
          if (ok) onCancel();
        }}
      >
        <Form.Item
          name="name"
          label="模板名称"
          rules={[{ required: true, message: "请输入模板名称" }]}
        >
          <Input placeholder="模板名称" />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea placeholder="描述" rows={3} />
        </Form.Item>
        <Form.Item
          name="category"
          label="分类"
          initialValue="general"
          rules={[{ required: true, message: "请输入分类" }]}
        >
          <Input placeholder="例如: general, rag, agent" />
        </Form.Item>
        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={submitting}>
              发布
            </Button>
            <Button onClick={onCancel}>取消</Button>
          </Space>
        </Form.Item>
      </Form>
    </Modal>
  );
}
