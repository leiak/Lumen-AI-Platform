"use client";

import { Modal, Form, Input, Space, Button } from "antd";
import { useEffect } from "react";

interface Props {
  open: boolean;
  onCancel: () => void;
  onSubmit: (values: { name: string; description?: string }) => Promise<boolean>;
}

/**
 * M30b: create-workflow modal.
 *
 * Uses a single Form instance bound to the modal's open state so
 * resetting it on close is automatic.
 */
export function CreateWorkflowModal({ open, onCancel, onSubmit }: Props) {
  const [form] = Form.useForm();

  useEffect(() => {
    if (!open) {
      form.resetFields();
    }
  }, [open, form]);

  return (
    <Modal
      title="创建工作流"
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
          label="名称"
          rules={[{ required: true, message: "请输入名称" }]}
        >
          <Input placeholder="请输入工作流名称" autoFocus />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea placeholder="请输入描述" rows={3} />
        </Form.Item>
        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit">
              创建
            </Button>
            <Button onClick={onCancel}>取消</Button>
          </Space>
        </Form.Item>
      </Form>
    </Modal>
  );
}
