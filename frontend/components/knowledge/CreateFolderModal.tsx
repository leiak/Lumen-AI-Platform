"use client";

// M38.2: 新建 folder 的轻量表单 —— name + 可选 parent_id + description。

import { useEffect } from "react";
import { Modal, Form, Input, Select, TreeSelect } from "antd";
import type {
  DocumentFolderCreatePayload,
  DocumentFolderTreeNode,
} from "@/types/folder";

const { TextArea } = Input;

export interface CreateFolderModalProps {
  open: boolean;
  kbId: number;
  /** 用于「挂在哪个父 folder 下」下拉;根目录选 null。 */
  folders: DocumentFolderTreeNode[];
  /** 预先填的 parent_id,例如右键 menu 选「新建子文件夹」。 */
  defaultParentId?: number | null;
  onCancel: () => void;
  onSubmit: (payload: DocumentFolderCreatePayload) => Promise<void> | void;
}

function flattenForSelect(
  folders: DocumentFolderTreeNode[]
): { value: number; label: string }[] {
  const acc: { value: number; label: string }[] = [];
  const walk = (nodes: DocumentFolderTreeNode[], depth: number) => {
    for (const n of nodes) {
      acc.push({
        value: n.id,
        label: `${"　".repeat(depth)}${n.name}`,
      });
      if (n.children?.length) walk(n.children, depth + 1);
    }
  };
  walk(folders, 0);
  return acc;
}

export default function CreateFolderModal(props: CreateFolderModalProps) {
  const { open, kbId, folders, defaultParentId, onCancel, onSubmit } = props;
  const [form] = Form.useForm<DocumentFolderCreatePayload & { parent_choice: number | "root" }>();

  useEffect(() => {
    if (open) {
      form.resetFields();
      form.setFieldsValue({
        parent_choice: defaultParentId ?? "root",
        order_index: 0,
      });
    }
  }, [open, defaultParentId, form]);

  const parentOptions = [
    { value: "root" as const, label: "KB 根目录" },
    ...flattenForSelect(folders),
  ];

  return (
    <Modal
      title={`新建 folder (KB #${kbId})`}
      open={open}
      onCancel={onCancel}
      onOk={async () => {
        const v = await form.validateFields();
        const parent_id =
          v.parent_choice === "root" || v.parent_choice == null
            ? null
            : Number(v.parent_choice);
        await onSubmit({
          name: v.name,
          description: v.description,
          parent_id,
          order_index: v.order_index ?? 0,
        });
      }}
      okText="创建"
      cancelText="取消"
      destroyOnClose
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item
          name="name"
          label="名称"
          rules={[{ required: true, message: "请输入 folder 名" }]}
        >
          <Input placeholder="例如:产品文档 / API 规范 / FAQ" maxLength={100} />
        </Form.Item>
        <Form.Item name="parent_choice" label="父级">
          <Select options={parentOptions} />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <TextArea rows={2} maxLength={500} />
        </Form.Item>
        <Form.Item
          name="order_index"
          label="排序"
          tooltip="数字越小越靠前;默认 0"
        >
          <Select
            options={[
              { value: 0, label: "0 (最前)" },
              { value: 10, label: "10" },
              { value: 20, label: "20" },
              { value: 50, label: "50" },
              { value: 100, label: "100 (最后)" },
            ]}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}