// frontend/components/text2sql/DataSourceManager.tsx
// M33 — Text2Sql DataSource CRUD UI (T29)
"use client";

import { useState } from "react";
import {
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { EditOutlined, PlusOutlined, DeleteOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { text2SqlApi } from "@/services/text2sql";
import type {
  Text2SqlDataSource,
  Text2SqlDataSourceCreate,
} from "@/types/text2sql";

export function DataSourceManager() {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<Text2SqlDataSource | null>(null);
  const [creating, setCreating] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["text2sql-datasources"],
    queryFn: () => text2SqlApi.listDataSources({ page_size: 100 }),
  });

  const del = useMutation({
    mutationFn: (id: number) => text2SqlApi.deleteDataSource(id),
    onSuccess: () => {
      message.success("已删除");
      qc.invalidateQueries({ queryKey: ["text2sql-datasources"] });
    },
    onError: (e: Error) => {
      message.error(e.message);
    },
  });

  const items = data?.items ?? [];
  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setCreating(true)}
        >
          新建数据源
        </Button>
      </Space>
      <Table
        loading={isLoading}
        size="small"
        rowKey="id"
        dataSource={items}
        pagination={false}
        columns={[
          {
            title: "ID",
            dataIndex: "id",
            width: 60,
          },
          {
            title: "名称",
            dataIndex: "name",
            render: (v: string, r) => (
              <Space>
                <Typography.Text strong>{v}</Typography.Text>
                {!r.is_active && <Tag>已停用</Tag>}
              </Space>
            ),
          },
          {
            title: "库",
            dataIndex: "db_name",
            width: 100,
          },
          {
            title: "max_rows",
            dataIndex: "max_rows",
            width: 80,
          },
          {
            title: "timeout_ms",
            dataIndex: "timeout_ms",
            width: 100,
          },
          {
            title: "操作",
            width: 140,
            render: (_: unknown, r: Text2SqlDataSource) => (
              <Space>
                <Button
                  size="small"
                  icon={<EditOutlined />}
                  onClick={() => setEditing(r)}
                >
                  编辑
                </Button>
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => {
                    Modal.confirm({
                      title: "确认删除?",
                      content: `数据源 ${r.name} 删除后将无法恢复(若被历史查询引用则会被拒绝)。`,
                      onOk: () => del.mutate(r.id),
                    });
                  }}
                >
                  删除
                </Button>
              </Space>
            ),
          },
        ]}
      />
      <DataSourceFormModal
        open={creating}
        onClose={() => setCreating(false)}
        initial={null}
      />
      <DataSourceFormModal
        open={editing != null}
        onClose={() => setEditing(null)}
        initial={editing}
      />
    </>
  );
}

// --------------------------------------------------------------------------- //
// DataSourceFormModal — create / edit form                                     //
// --------------------------------------------------------------------------- //

export function DataSourceFormModal({
  open,
  onClose,
  initial,
}: {
  open: boolean;
  onClose: () => void;
  initial: Text2SqlDataSource | null;
}) {
  const [form] = Form.useForm<Text2SqlDataSourceCreate>();
  const qc = useQueryClient();
  const isEdit = !!initial;
  const createMut = useMutation({
    mutationFn: (body: Text2SqlDataSourceCreate) =>
      text2SqlApi.createDataSource(body),
    onSuccess: () => {
      message.success("已创建");
      qc.invalidateQueries({ queryKey: ["text2sql-datasources"] });
      onClose();
    },
    onError: (e: Error) => message.error(e.message),
  });
  const updateMut = useMutation({
    mutationFn: (body: Partial<Text2SqlDataSourceCreate>) => {
      if (!initial) throw new Error("missing id");
      return text2SqlApi.updateDataSource(initial.id, body);
    },
    onSuccess: () => {
      message.success("已更新");
      qc.invalidateQueries({ queryKey: ["text2sql-datasources"] });
      onClose();
    },
    onError: (e: Error) => message.error(e.message),
  });

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={isEdit ? "编辑数据源" : "新建数据源"}
      onOk={async () => {
        const values = await form.validateFields();
        if (isEdit) {
          updateMut.mutate(values);
        } else {
          createMut.mutate(values);
        }
      }}
      confirmLoading={createMut.isPending || updateMut.isPending}
      okText="保存"
      cancelText="取消"
      destroyOnClose
      afterOpenChange={(visible) => {
        if (visible) {
          if (initial) {
            form.setFieldsValue({
              name: initial.name,
              db_name: initial.db_name,
              max_rows: initial.max_rows,
              timeout_ms: initial.timeout_ms,
              description: initial.description ?? undefined,
              is_active: initial.is_active,
            });
          } else {
            form.resetFields();
          }
        }
      }}
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="name"
          label="名称"
          rules={[{ required: true, max: 100 }]}
        >
          <Input placeholder="如: 默认 ai_platform" />
        </Form.Item>
        <Form.Item
          name="db_name"
          label="库名"
          tooltip="当前只支持 ai_platform"
          rules={[{ required: true }]}
        >
          <Input placeholder="ai_platform" />
        </Form.Item>
        <Form.Item
          name="max_rows"
          label="max_rows"
          tooltip="自动 LIMIT 上限"
          rules={[{ required: true, type: "number", min: 1, max: 10000 }]}
        >
          <InputNumber style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item
          name="timeout_ms"
          label="timeout_ms"
          tooltip="MAX_EXECUTION_TIME hint"
          rules={[{ required: true, type: "number", min: 100, max: 60000 }]}
        >
          <InputNumber style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={3} />
        </Form.Item>
        <Form.Item
          name="is_active"
          label="启用"
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  );
}
