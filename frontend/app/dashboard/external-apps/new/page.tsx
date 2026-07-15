"use client";

import { useEffect, useState } from "react";
import { Form, Input, Button, Select, InputNumber, Card, Space, App, Alert } from "antd";
import { useRouter } from "next/navigation";
import {
  externalAppApi,
  listAgentOptions,
  listTeamOptions,
} from "@/services/externalApp";
import type { ExternalAppCreated } from "@/types/api";
import SecretRevealModal from "@/components/external-apps/SecretRevealModal";

interface CreateValues {
  name: string;
  description?: string;
  allowed_origins?: string[];
  rate_limit_per_min?: number;
  allowed_agent_ids?: number[];
  allowed_team_ids?: number[];
}

export default function NewExternalAppPage() {
  const { message } = App.useApp();
  const router = useRouter();
  const [form] = Form.useForm<CreateValues>();
  const [submitting, setSubmitting] = useState(false);
  const [created, setCreated] = useState<ExternalAppCreated | null>(null);
  const [agentOptions, setAgentOptions] = useState<{ id: number; name: string }[]>([]);
  const [teamOptions, setTeamOptions] = useState<{ id: number; name: string }[]>([]);

  useEffect(() => {
    Promise.all([listAgentOptions(), listTeamOptions()])
      .then(([agents, teams]) => {
        setAgentOptions(agents);
        setTeamOptions(teams);
      })
      .catch((e: any) => message.error(`加载选项失败: ${e?.message ?? e}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const serverUrl = typeof window !== "undefined" ? window.location.origin : "";

  async function onSubmit(values: CreateValues) {
    setSubmitting(true);
    try {
      const out = await externalAppApi.create({
        name: values.name,
        description: values.description,
        allowed_origins: values.allowed_origins || [],
        allowed_agent_ids: values.allowed_agent_ids || [],
        allowed_team_ids: values.allowed_team_ids || [],
        rate_limit_per_min: values.rate_limit_per_min ?? 60,
        scopes: "chat:stream,chat:upload,conv:read",
      });
      setCreated(out);
    } catch (e: any) {
      message.error(`创建失败: ${e?.message ?? e}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ padding: 24, maxWidth: 720 }}>
      <Card title="新建外部应用">
        <Form
          form={form}
          layout="vertical"
          onFinish={onSubmit}
          initialValues={{ rate_limit_per_min: 60 }}
        >
          <Form.Item label="名称" name="name" rules={[{ required: true }]}>
            <Input placeholder="如:官网客服" />
          </Form.Item>
          <Form.Item label="描述" name="description">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item
            label="授权 Origins"
            name="allowed_origins"
            tooltip="形如 https://shop.example.com 或 https://*.example.com"
          >
            <Select mode="tags" placeholder="按回车添加 origin" />
          </Form.Item>
          <Form.Item
            label="允许的 Agents"
            name="allowed_agent_ids"
            tooltip="嵌入 chat 时的可选 Agent 白名单;留空则不允许任何 Agent"
          >
            <Select
              mode="multiple"
              showSearch
              placeholder="选择允许的 Agent"
              options={agentOptions.map((a) => ({ value: a.id, label: a.name }))}
              filterOption={(input, option) =>
                ((option?.label as string) ?? "").toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>
          <Form.Item
            label="允许的 Teams"
            name="allowed_team_ids"
            tooltip="嵌入 chat 时的可选 Team 白名单;留空则不允许任何 Team"
          >
            <Select
              mode="multiple"
              showSearch
              placeholder="选择允许的 Team"
              options={teamOptions.map((t) => ({ value: t.id, label: t.name }))}
              filterOption={(input, option) =>
                ((option?.label as string) ?? "").toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>
          <Form.Item label="速率 (次/分)" name="rate_limit_per_min">
            <InputNumber min={1} max={10000} style={{ width: 200 }} />
          </Form.Item>
          <Form.Item shouldUpdate noStyle>
            {() => {
              const agentIds: number[] = form.getFieldValue("allowed_agent_ids") ?? [];
              const teamIds: number[] = form.getFieldValue("allowed_team_ids") ?? [];
              if (agentIds.length > 0 || teamIds.length > 0) return null;
              return (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 16 }}
                  message="该 app 当前没有可用的 Agent 或 Team,保存后对话会返回 400"
                />
              );
            }}
          </Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={submitting}>
              创建
            </Button>
            <Button onClick={() => router.push("/dashboard/external-apps")}>
              取消
            </Button>
          </Space>
        </Form>
      </Card>
      {created && (
        <SecretRevealModal
          open={!!created}
          appKey={created.app_key}
          appSecret={created.app_secret_plain}
          serverUrl={serverUrl}
          onAck={() => router.push(`/dashboard/external-apps/${created.id}`)}
        />
      )}
    </div>
  );
}
