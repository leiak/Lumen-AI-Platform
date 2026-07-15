"use client";

import { Card, Form, Input, Button, message, Switch, Space } from "antd";
import { useState, useEffect } from "react";
import { settingsApi, SystemSettings, SecuritySettings } from "@/services/settings";
import ChatModelSelect from "@/components/ChatModelSelect";
import EmbeddingModelSelect from "@/components/EmbeddingModelSelect";

export default function SettingsPage() {
  const [loading, setLoading] = useState(false);
  const [securityLoading, setSecurityLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [form] = Form.useForm();
  const [securityForm] = Form.useForm();

  useEffect(() => {
    loadSettings();
    loadSecuritySettings();
  }, []);

  const loadSettings = async () => {
    setInitialLoading(true);
    try {
      const response = await settingsApi.get();
      if (response.data?.data) {
        form.setFieldsValue(response.data.data);
      }
    } catch (error) {
      message.error("加载系统设置失败");
    } finally {
      setInitialLoading(false);
    }
  };

  const loadSecuritySettings = async () => {
    try {
      const response = await settingsApi.getSecuritySettings();
      if (response.data?.data) {
        securityForm.setFieldsValue(response.data.data);
      }
    } catch (error) {
      message.error("加载安全设置失败");
    }
  };

  const onFinish = async (values: Partial<SystemSettings>) => {
    setLoading(true);
    try {
      await settingsApi.update(values);
      message.success("设置保存成功");
    } catch (error) {
      message.error("保存失败");
    } finally {
      setLoading(false);
    }
  };

  const onSecurityFinish = async (values: Partial<SecuritySettings>) => {
    setSecurityLoading(true);
    try {
      await settingsApi.updateSecuritySettings(values);
      message.success("安全设置保存成功");
    } catch (error) {
      message.error("保存失败");
    } finally {
      setSecurityLoading(false);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Card title="系统设置" style={{ maxWidth: 600 }}>
        <Form
          layout="vertical"
          form={form}
          onFinish={onFinish}
          initialValues={{
            system_name: "Lumen AI Platform",
            system_description: "",
            default_model: null,
            embedding_model: null,
            chat_history_days: 30,
          }}
        >
          <Form.Item label="系统名称" name="system_name">
            <Input placeholder="Lumen AI Platform" />
          </Form.Item>

          <Form.Item label="系统描述" name="system_description">
            <Input.TextArea placeholder="基于 LangChain + React 的 AI 中台" rows={3} />
          </Form.Item>

          <Form.Item label="默认聊天模型" name="default_model">
            <ChatModelSelect />
          </Form.Item>

          <Form.Item label="Embedding 模型" name="embedding_model">
            <EmbeddingModelSelect />
          </Form.Item>

          <Form.Item label="会话历史保留天数" name="chat_history_days">
            <Input type="number" placeholder="30" />
          </Form.Item>

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={loading}>
                保存设置
              </Button>
              <Button onClick={() => message.info("重置功能开发中")}>
                重置
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>

      <Card title="安全设置" style={{ maxWidth: 600, marginTop: 24 }}>
        <Form
          layout="vertical"
          form={securityForm}
          onFinish={onSecurityFinish}
        >
          <Form.Item label="强制密码复杂度" name="enforce_password_complexity" valuePropName="checked">
            <Switch />
          </Form.Item>

          <Form.Item label="密码最小长度" name="min_password_length">
            <Input type="number" placeholder="8" style={{ width: 100 }} />
          </Form.Item>

          <Form.Item label="登录失败锁定次数" name="login_fail_lock_count">
            <Input type="number" placeholder="5" style={{ width: 100 }} />
          </Form.Item>

          <Form.Item label="Token 过期时间(分钟)" name="token_expire_minutes">
            <Input type="number" placeholder="30" style={{ width: 100 }} />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit" loading={securityLoading}>
              保存安全设置
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}