"use client";

import { Modal, Card, Form, Input, Button, Table, Tag, Popconfirm, Space } from "antd";
import { useEffect } from "react";
import { Schedule } from "../hooks/useWorkflowSchedules";

interface Props {
  open: boolean;
  schedules: Schedule[];
  submitting: boolean;
  deletingId: number | null;
  onCancel: () => void;
  onCreate: (values: { name: string; cron_expression: string }) => Promise<boolean>;
  onDelete: (scheduleId: number) => void;
}

/**
 * M30b: schedule CRUD modal. The list + form are in the same card so
 * the user can see the existing schedules while creating a new one.
 */
export function ScheduleModal({
  open,
  schedules,
  submitting,
  deletingId,
  onCancel,
  onCreate,
  onDelete,
}: Props) {
  const [form] = Form.useForm();

  useEffect(() => {
    if (!open) form.resetFields();
  }, [open, form]);

  return (
    <Modal
      title="定时调度管理"
      open={open}
      onCancel={onCancel}
      footer={null}
      width={600}
      destroyOnHidden
    >
      <Card size="small" style={{ marginBottom: 16 }}>
        <Form
          form={form}
          layout="inline"
          onFinish={async (values) => {
            const ok = await onCreate(values);
            if (ok) form.resetFields();
          }}
        >
          <Form.Item
            name="name"
            rules={[{ required: true, message: "请输入名称" }]}
          >
            <Input placeholder="任务名称" style={{ width: 140 }} />
          </Form.Item>
          <Form.Item
            name="cron_expression"
            rules={[{ required: true, message: "请输入Cron表达式" }]}
          >
            <Input placeholder="0 9 * * *" style={{ width: 160 }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={submitting}>
              添加
            </Button>
          </Form.Item>
        </Form>
        <div style={{ fontSize: 12, color: "#888", marginTop: 8 }}>
          Cron格式: 分 时 日 月 周 (例: "0 9 * * *" 表示每天 9:00 执行)
        </div>
      </Card>
      <Table
        dataSource={schedules}
        rowKey="id"
        size="small"
        columns={[
          { title: "名称", dataIndex: "name", key: "name" },
          { title: "Cron", dataIndex: "cron_expression", key: "cron_expression" },
          {
            title: "状态",
            dataIndex: "is_active",
            key: "is_active",
            render: (v: boolean) => (
              <Tag color={v ? "green" : "red"}>{v ? "启用" : "禁用"}</Tag>
            ),
          },
          {
            title: "下次执行",
            dataIndex: "next_run_at",
            key: "next_run_at",
            render: (v: string | null | undefined) =>
              v ? new Date(v).toLocaleString() : "-",
          },
          {
            title: "操作",
            key: "action",
            render: (_, record) => (
              <Popconfirm
                title="确认删除?"
                onConfirm={() => onDelete(record.id)}
              >
                <Button size="small" danger loading={deletingId === record.id}>
                  删除
                </Button>
              </Popconfirm>
            ),
          },
        ]}
      />
    </Modal>
  );
}
