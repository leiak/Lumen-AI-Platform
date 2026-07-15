// frontend/app/dashboard/customer/settings/page.tsx
// M33 — 客户自定义字段管理.
//
// Spec §5.4 — Table + 新建/编辑 Modal(field_key 创建后不可改, type 改了 customer 引用会 422).
"use client";

import { useState } from "react";
import {
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  App,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { customerFieldApi } from "@/services/customer";
import type {
  CustomerFieldDefinitionCreate,
  CustomerFieldDefinitionResponse,
  CustomerFieldDefinitionUpdate,
  FieldType,
} from "@/types/customer";

const FIELD_TYPE_OPTIONS: { value: FieldType; label: string; color: string }[] = [
  { value: "text", label: "文本", color: "blue" },
  { value: "number", label: "数字", color: "cyan" },
  { value: "date", label: "日期", color: "purple" },
  { value: "select", label: "单选", color: "green" },
  { value: "multiselect", label: "多选", color: "gold" },
  { value: "textarea", label: "长文本", color: "orange" },
];

export default function CustomerFieldSettingsPage() {
  const qc = useQueryClient();
  const { message: toast } = App.useApp();
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<CustomerFieldDefinitionResponse | null>(null);
  const [form] = Form.useForm();

  const { data, isLoading } = useQuery({
    queryKey: ["customer", "field-defs"],
    queryFn: () => customerFieldApi.list(1, 100, true),
  });

  const handleCreate = async () => {
    const values = await form.validateFields();
    try {
      const payload: CustomerFieldDefinitionCreate = {
        field_key: values.field_key,
        field_label: values.field_label,
        field_type: values.field_type,
        options: values.options,
        required: values.required ?? false,
        order_index: values.order_index ?? 0,
      };
      await customerFieldApi.create(payload);
      toast.success("字段已创建");
      setCreateOpen(false);
      form.resetFields();
      qc.invalidateQueries({ queryKey: ["customer", "field-defs"] });
    } catch (err: any) {
      if (err?.errorFields) return;
      toast.error(err?.message || "创建失败");
    }
  };

  const handleEdit = (row: CustomerFieldDefinitionResponse) => {
    setEditing(row);
    form.setFieldsValue({
      field_key: row.field_key,
      field_label: row.field_label,
      field_type: row.field_type,
      options: row.options,
      required: row.required,
      order_index: row.order_index,
      is_active: row.is_active,
    });
  };

  const handleUpdate = async () => {
    if (!editing) return;
    const values = await form.validateFields();
    try {
      const payload: CustomerFieldDefinitionUpdate = {
        field_label: values.field_label,
        field_type: values.field_type,
        options: values.options,
        required: values.required,
        order_index: values.order_index,
        is_active: values.is_active,
      };
      await customerFieldApi.update(editing.id, payload);
      toast.success("字段已更新");
      setEditing(null);
      form.resetFields();
      qc.invalidateQueries({ queryKey: ["customer", "field-defs"] });
    } catch (err: any) {
      if (err?.errorFields) return;
      toast.error(err?.message || "更新失败");
    }
  };

  const handleDelete = async (row: CustomerFieldDefinitionResponse) => {
    try {
      await customerFieldApi.delete(row.id);
      toast.success("字段已删除");
      qc.invalidateQueries({ queryKey: ["customer", "field-defs"] });
    } catch (err: any) {
      toast.error(err?.message || "删除失败");
    }
  };

  const handleToggleActive = async (row: CustomerFieldDefinitionResponse, checked: boolean) => {
    try {
      await customerFieldApi.update(row.id, { is_active: checked });
      toast.success(checked ? "已启用" : "已禁用");
      qc.invalidateQueries({ queryKey: ["customer", "field-defs"] });
    } catch (err: any) {
      toast.error(err?.message || "切换失败");
    }
  };

  const columns = [
    { title: "字段 Key", dataIndex: "field_key", key: "field_key", width: 180 },
    { title: "显示名", dataIndex: "field_label", key: "field_label", width: 160 },
    {
      title: "类型",
      dataIndex: "field_type",
      key: "field_type",
      width: 100,
      render: (t: string) => {
        const opt = FIELD_TYPE_OPTIONS.find((o) => o.value === t);
        return opt ? <Tag color={opt.color}>{opt.label}</Tag> : <Tag>{t}</Tag>;
      },
    },
    {
      title: "选项",
      dataIndex: "options",
      key: "options",
      render: (opts?: string[] | null) =>
        opts?.length ? opts.map((o) => <Tag key={o}>{o}</Tag>) : "—",
    },
    {
      title: "必填",
      dataIndex: "required",
      key: "required",
      width: 70,
      render: (r: boolean) => (r ? <Tag color="red">必填</Tag> : "否"),
    },
    { title: "顺序", dataIndex: "order_index", key: "order_index", width: 70 },
    {
      title: "启用",
      dataIndex: "is_active",
      key: "is_active",
      width: 90,
      render: (active: boolean, row: CustomerFieldDefinitionResponse) => (
        <Switch
          checked={active}
          onChange={(checked) => handleToggleActive(row, checked)}
          size="small"
        />
      ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 160,
      render: (t: string) => dayjs(t).format("YYYY-MM-DD HH:mm"),
    },
    {
      title: "操作",
      key: "actions",
      width: 160,
      render: (_: any, row: CustomerFieldDefinitionResponse) => (
        <Space size="small">
          <Button size="small" onClick={() => handleEdit(row)}>
            编辑
          </Button>
          <Button size="small" danger onClick={() => handleDelete(row)}>
            删除
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginTop: 0 }}>自定义字段管理</h2>
      <p style={{ color: "#999" }}>
        配置客户档案的自定义字段。field_key 创建后不可修改,改 type 时若已有客户引用会失败(422)。
      </p>

      <Space style={{ marginBottom: 16 }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            form.resetFields();
            setEditing(null);
            setCreateOpen(true);
          }}
        >
          新建字段
        </Button>
      </Space>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={data?.items ?? []}
        loading={isLoading}
        pagination={{
          pageSize: 100,
          showSizeChanger: false,
        }}
      />

      <Modal
        title={editing ? "编辑字段" : "新建字段"}
        open={createOpen || !!editing}
        onCancel={() => {
          setCreateOpen(false);
          setEditing(null);
          form.resetFields();
        }}
        onOk={editing ? handleUpdate : handleCreate}
        okText="保存"
        cancelText="取消"
        destroyOnClose
        width={560}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            label="字段 Key(英文 + 下划线,小写开头)"
            name="field_key"
            rules={[
              { required: true, pattern: /^[a-z][a-z0-9_]{0,49}$/, message: "格式: 小写字母开头 + [a-z0-9_]" },
            ]}
            extra={editing ? "field_key 创建后不可修改" : undefined}
          >
            <Input disabled={!!editing} placeholder="customer_ltv" />
          </Form.Item>
          <Form.Item
            label="显示名"
            name="field_label"
            rules={[{ required: true, max: 100 }]}
          >
            <Input placeholder="客户终身价值" />
          </Form.Item>
          <Form.Item
            label="类型"
            name="field_type"
            rules={[{ required: true }]}
          >
            <Select
              options={FIELD_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
              placeholder="选择字段类型"
            />
          </Form.Item>
          <Form.Item
            label="选项(select / multiselect 时必填)"
            name="options"
          >
            <Select mode="tags" placeholder="Enter 添加选项" />
          </Form.Item>
          <Space>
            <Form.Item label="必填" name="required" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item label="顺序" name="order_index">
              <InputNumber min={0} />
            </Form.Item>
            {editing && (
              <Form.Item label="启用" name="is_active" valuePropName="checked">
                <Switch />
              </Form.Item>
            )}
          </Space>
        </Form>
      </Modal>
    </div>
  );
}