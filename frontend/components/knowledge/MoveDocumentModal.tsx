"use client";

// M38.2: 把一个 doc 从当前 folder 移到目标 folder(或 KB 根)。
//
// 简化:target 直接渲染成扁平 select,因为深层级场景在 M38.2 范围
// 里很罕见,recursive TreeSelect 跟 FolderPicker 这种 UX 留到 M38.3。

import { useEffect } from "react";
import { Modal, Form, Select, Typography } from "antd";
import type { DocumentFolderTreeNode, DocumentMovePayload } from "@/types/folder";

const { Text } = Typography;

export interface MoveDocumentModalProps {
  open: boolean;
  documentId: number;
  documentName?: string;
  /** Source folder; null = KB 根。 */
  currentFolderId: number | null;
  /** Possible destinations; KB-root option is always prepended. */
  folders: DocumentFolderTreeNode[];
  onCancel: () => void;
  onSubmit: (payload: DocumentMovePayload) => Promise<void> | void;
}

function flatten(
  folders: DocumentFolderTreeNode[]
): { value: number; label: string; disabled?: boolean }[] {
  const acc: { value: number; label: string; disabled?: boolean }[] = [];
  const walk = (nodes: DocumentFolderTreeNode[], depth: number) => {
    for (const n of nodes) {
      acc.push({
        value: n.id,
        label: `${"　".repeat(depth)}${n.name} (${n.document_count})`,
      });
      if (n.children?.length) walk(n.children, depth + 1);
    }
  };
  walk(folders, 0);
  return acc;
}

export default function MoveDocumentModal(props: MoveDocumentModalProps) {
  const {
    open,
    documentId,
    documentName,
    currentFolderId,
    folders,
    onCancel,
    onSubmit,
  } = props;

  const [form] = Form.useForm<{ target: number | "root" }>();

  useEffect(() => {
    if (open) {
      form.resetFields();
      form.setFieldsValue({ target: currentFolderId ?? "root" });
    }
  }, [open, currentFolderId, form]);

  const options = [
    { value: "root" as const, label: "KB 根目录" },
    ...flatten(folders),
  ];

  return (
    <Modal
      title={`移动文档 (#${documentId})`}
      open={open}
      onCancel={onCancel}
      onOk={async () => {
        const v = await form.validateFields();
        await onSubmit({
          target_folder_id: v.target === "root" ? null : Number(v.target),
        });
      }}
      okText="移动"
      cancelText="取消"
      destroyOnClose
    >
      {documentName && (
        <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
          {documentName}
        </Text>
      )}
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item name="target" label="目标 folder">
          <Select
            options={options}
            showSearch
            optionFilterProp="label"
            placeholder="选择目标 folder (或 KB 根)"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}