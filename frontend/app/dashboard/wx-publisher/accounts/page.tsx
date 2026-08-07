// frontend/app/dashboard/wx-publisher/accounts/page.tsx
// M32 — 公众号助手 — 公众号账号管理页.
//
// Spec §5.6 — Table + 新建/编辑 Modal + AppSecret 一次性显示 Modal.
"use client";

import { useState } from "react";
import {
  Button,
  Space,
  Modal,
  Form,
  Input,
  Select,
  Switch,
  Card,
  App,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { accountApi } from "@/services/wx-publisher";
import { authApi } from "@/services/auth";
import { AccountTable } from "@/components/wx-publisher/AccountTable";
import { AppSecretRevealModal } from "@/components/wx-publisher/AppSecretRevealModal";
import type {
  WxAccountCreate,
  WxAccountUpdate,
  WxAccountResponse,
  WxAccountType,
} from "@/types/wx-publisher";

const APP_ID_PATTERN = /^wx[a-z0-9]{16,32}$/;

export default function AccountsPage() {
  const qc = useQueryClient();
  const { message: toast } = App.useApp();
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<WxAccountResponse | null>(null);
  const [reveal, setReveal] = useState<{
    open: boolean;
    secret: string;
    appId: string;
  }>({ open: false, secret: "", appId: "" });
  const [form] = Form.useForm();

  const { data, isLoading } = useQuery({
    queryKey: ["wx-publisher", "accounts"],
    queryFn: () => accountApi.list({ page: 1, page_size: 100 }),
  });

  // 当前用户 — 决定是否展示「永久删除」按钮 (admin-only hard delete)
  const { data: meData } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: async () => {
      const res = await authApi.getMe();
      return res.data?.data;
    },
    staleTime: 5 * 60 * 1000,
  });
  const isAdmin = Boolean(meData?.is_superuser);

  const handleCreate = async () => {
    const values = await form.validateFields();
    try {
      const payload: WxAccountCreate = {
        name: values.name,
        app_id: values.app_id,
        app_secret: values.app_secret,
        account_type: values.account_type ?? "subscription",
        is_mock: values.is_mock ?? true,
        ip_whitelist: values.ip_whitelist
          ? values.ip_whitelist
              .split("\n")
              .map((s: string) => s.trim())
              .filter(Boolean)
          : null,
      };
      const created = await accountApi.create(payload);
      toast.success("账号已创建");
      setCreateOpen(false);
      form.resetFields();
      qc.invalidateQueries({ queryKey: ["wx-publisher", "accounts"] });
      // 一次性显示 AppSecret — 后端响应里 AppSecret 不会回返明文,
      // 所以这里使用 form 填入的值 (前端在创建时短暂持有).
      setReveal({
        open: true,
        secret: values.app_secret,
        appId: created.app_id,
      });
    } catch (err: any) {
      toast.error(err?.message || "创建失败");
    }
  };

  const handleUpdate = async () => {
    if (!editing) return;
    const values = await form.validateFields();
    try {
      const payload: WxAccountUpdate = {
        name: values.name,
        is_active: values.is_active,
        is_mock: values.is_mock,
        ip_whitelist: values.ip_whitelist
          ? values.ip_whitelist
              .split("\n")
              .map((s: string) => s.trim())
              .filter(Boolean)
          : null,
      };
      await accountApi.update(editing.id, payload);
      toast.success("已更新");
      setEditing(null);
      form.resetFields();
      qc.invalidateQueries({ queryKey: ["wx-publisher", "accounts"] });
    } catch (err: any) {
      toast.error(err?.message || "更新失败");
    }
  };

  const handleVerify = async (id: number) => {
    try {
      const res = await accountApi.verify(id);
      if (res.valid) {
        toast.success("AppID/AppSecret 校验通过");
      } else {
        toast.warning(`校验未通过: ${res.message}`);
      }
      qc.invalidateQueries({ queryKey: ["wx-publisher", "accounts"] });
    } catch (err: any) {
      toast.error(err?.message || "校验失败");
    }
  };

  const handleToggleMock = async (id: number, isMock: boolean) => {
    try {
      await accountApi.update(id, { is_mock: isMock });
      toast.success(isMock ? "已切到 Mock 模式" : "已切到 Real 模式");
      qc.invalidateQueries({ queryKey: ["wx-publisher", "accounts"] });
    } catch (err: any) {
      toast.error(err?.message || "切换失败");
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await accountApi.delete(id);
      toast.success("已停用");
      qc.invalidateQueries({ queryKey: ["wx-publisher", "accounts"] });
    } catch (err: any) {
      toast.error(err?.message || "停用失败");
    }
  };

  const handlePurge = async (id: number) => {
    try {
      const summary = await accountApi.purge(id);
      toast.success(
        `已永久删除账号 (清理 ${summary.deleted_publish_records} 条发布记录,` +
          `${summary.drafts_set_null} 个草稿被解绑)`
      );
      qc.invalidateQueries({ queryKey: ["wx-publisher", "accounts"] });
    } catch (err: any) {
      toast.error(err?.message || "永久删除失败");
    }
  };

  const openEdit = (row: WxAccountResponse) => {
    setEditing(row);
    form.setFieldsValue({
      name: row.name,
      is_active: row.is_active,
      is_mock: row.is_mock,
    });
  };

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginTop: 0 }}>公众号账号</h2>

      <Space style={{ marginBottom: 16, width: "100%" }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            form.resetFields();
            setCreateOpen(true);
          }}
        >
          新建账号
        </Button>
      </Space>

      <Card styles={{ body: { padding: 0 } }}>
        <AccountTable
          items={data?.items ?? []}
          loading={isLoading}
          isAdmin={isAdmin}
          onEdit={openEdit}
          onDelete={handleDelete}
          onPurge={handlePurge}
          onVerify={handleVerify}
          onToggleMock={handleToggleMock}
        />
      </Card>

      <Modal
        title="新建公众号账号"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreate}
        okText="保存"
        cancelText="取消"
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ account_type: "subscription", is_mock: true }}
        >
          <Form.Item
            name="name"
            label="账号名"
            rules={[{ required: true, message: "请输入账号名" }]}
          >
            <Input placeholder="例: 科技早班车" />
          </Form.Item>
          <Form.Item
            name="app_id"
            label="AppID"
            rules={[
              { required: true, message: "请输入 AppID" },
              {
                pattern: APP_ID_PATTERN,
                message: "格式: wx 开头 + 16-32 位小写字母数字",
              },
            ]}
          >
            <Input placeholder="wx1234567890abcdef" />
          </Form.Item>
          <Form.Item
            name="app_secret"
            label="AppSecret"
            rules={[
              { required: true, message: "请输入 AppSecret" },
              { min: 20, max: 100, message: "长度 20-100" },
            ]}
          >
            <Input.Password placeholder="仅创建时显示, 后续不再以明文展示" />
          </Form.Item>
          <Form.Item name="account_type" label="账号类型">
            <Select
              options={[
                { value: "subscription", label: "订阅号" },
                { value: "service", label: "服务号" },
                { value: "enterprise", label: "企业号" },
              ]}
            />
          </Form.Item>
          <Form.Item name="is_mock" label="Mock 模式" valuePropName="checked">
            <Switch checkedChildren="Mock" unCheckedChildren="Real" />
          </Form.Item>
          <Form.Item name="ip_whitelist" label="IP 白名单 (一行一个)">
            <Input.TextArea rows={3} placeholder="1.2.3.4" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={editing ? `编辑账号: ${editing.name}` : "编辑账号"}
        open={!!editing}
        onCancel={() => setEditing(null)}
        onOk={handleUpdate}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="账号名"
            rules={[{ required: true, message: "请输入账号名" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="is_mock" label="Mock 模式" valuePropName="checked">
            <Switch checkedChildren="Mock" unCheckedChildren="Real" />
          </Form.Item>
          <Form.Item name="ip_whitelist" label="IP 白名单 (一行一个)">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>

      <AppSecretRevealModal
        open={reveal.open}
        appSecret={reveal.secret}
        appId={reveal.appId}
        onClose={() => setReveal({ open: false, secret: "", appId: "" })}
      />
    </div>
  );
}