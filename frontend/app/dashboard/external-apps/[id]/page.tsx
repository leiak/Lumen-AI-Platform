"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Card,
  Form,
  Input,
  Button,
  Select,
  InputNumber,
  Switch,
  Tabs,
  Space,
  App,
  Popconfirm,
  Alert,
} from "antd";
import { KeyOutlined } from "@ant-design/icons";
import {
  externalAppApi,
  listAgentOptions,
  listTeamOptions,
} from "@/services/externalApp";
import type { ExternalApp, ExternalAppCreated } from "@/types/api";
import SecretRevealModal from "@/components/external-apps/SecretRevealModal";
import UsageTab from "@/components/external-apps/UsageTab";

type BasicValues = { name: string; description?: string; is_active?: boolean };
type ScopeValues = {
  allowed_origins?: string[];
  rate_limit_per_min?: number;
  allowed_agent_ids?: number[];
  allowed_team_ids?: number[];
};

export default function ExternalAppDetailPage() {
  const { id: idStr } = useParams<{ id: string }>();
  const id = Number(idStr);
  // MEMORY.md pitfall: antd v5 + Next.js 15 App Router static `message`
  // import does NOT render under React strict mode. Use App.useApp().
  const { message } = App.useApp();
  const router = useRouter();
  const [app, setApp] = useState<ExternalApp | null>(null);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [regenerated, setRegenerated] = useState<ExternalAppCreated | null>(null);
  const [agentOptions, setAgentOptions] = useState<{ id: number; name: string }[]>([]);
  const [teamOptions, setTeamOptions] = useState<{ id: number; name: string }[]>([]);

  async function load() {
    try {
      const [a, agents, teams] = await Promise.all([
        externalAppApi.get(id),
        listAgentOptions(),
        listTeamOptions(),
      ]);
      setApp(a);
      setAgentOptions(agents);
      setTeamOptions(teams);
      form.setFieldsValue({
        name: a.name,
        description: a.description,
        allowed_origins: a.allowed_origins,
        rate_limit_per_min: a.rate_limit_per_min,
        is_active: a.is_active,
        allowed_agent_ids: a.allowed_agent_ids ?? [],
        allowed_team_ids: a.allowed_team_ids ?? [],
      });
    } catch (e) {
      message.error(`加载失败: ${(e as Error)?.message ?? e}`);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function onSaveBasic(values: BasicValues) {
    setSaving(true);
    try {
      await externalAppApi.update(id, values);
      message.success("已保存(CORS 缓存最多 60s 生效)");
      load();
    } catch (e) {
      message.error(`保存失败: ${(e as Error)?.message ?? e}`);
    } finally {
      setSaving(false);
    }
  }

  async function onSaveScope(values: ScopeValues) {
    setSaving(true);
    try {
      await externalAppApi.update(id, values);
      message.success("已保存(CORS 缓存最多 60s 生效)");
      load();
    } catch (e) {
      message.error(`保存失败: ${(e as Error)?.message ?? e}`);
    } finally {
      setSaving(false);
    }
  }

  async function onRegenerate() {
    try {
      const out = await externalAppApi.regenerateSecret(id);
      setRegenerated(out);
      message.success("新密钥已生成");
    } catch (e) {
      message.error(`重置失败: ${(e as Error)?.message ?? e}`);
    }
  }

  if (!app) return <div style={{ padding: 24 }}>加载中…</div>;
  const serverUrl = typeof window !== "undefined" ? window.location.origin : "";

  return (
    <div style={{ padding: 24, maxWidth: 900 }}>
      <Space style={{ marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>{app.name}</h2>
        <Popconfirm
          title="重置密钥?"
          description="老 secret 将即刻失效"
          onConfirm={onRegenerate}
        >
          <Button danger icon={<KeyOutlined />}>
            重置密钥
          </Button>
        </Popconfirm>
      </Space>
      <Tabs
        items={[
          {
            key: "basic",
            label: "基础信息",
            children: (
              <Card>
                <Form form={form} layout="vertical" onFinish={onSaveBasic}>
                  <Form.Item label="名称" name="name" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                  <Form.Item label="描述" name="description">
                    <Input.TextArea rows={2} />
                  </Form.Item>
                  <Form.Item label="App Key">
                    <Input value={app.app_key} readOnly />
                  </Form.Item>
                  <Form.Item label="状态" name="is_active" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" loading={saving}>
                    保存
                  </Button>
                </Form>
              </Card>
            ),
          },
          {
            key: "scope",
            label: "授权范围",
            children: (
              <Card>
                <Form form={form} layout="vertical" onFinish={onSaveScope}>
                  <Form.Item
                    label="Origins"
                    name="allowed_origins"
                    tooltip="形如 https://shop.example.com 或 https://*.example.com"
                  >
                    <Select mode="tags" placeholder="https://example.com" />
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
                        ((option?.label as string) ?? "")
                          .toLowerCase()
                          .includes(input.toLowerCase())
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
                        ((option?.label as string) ?? "")
                          .toLowerCase()
                          .includes(input.toLowerCase())
                      }
                    />
                  </Form.Item>
                  <Form.Item label="速率 (次/分)" name="rate_limit_per_min">
                    <InputNumber min={1} max={10000} />
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
                  <Button type="primary" htmlType="submit" loading={saving}>
                    保存
                  </Button>
                </Form>
                <Alert
                  type="info"
                  showIcon
                  style={{ marginTop: 16 }}
                  message="保存后 CORS 缓存最多 60s 生效"
                />
              </Card>
            ),
          },
          {
            key: "usage",
            label: "用量统计",
            children: <UsageTab appId={id} />,
          },
        ]}
      />

      {regenerated && (
        <SecretRevealModal
          open={!!regenerated}
          appKey={regenerated.app_key}
          appSecret={regenerated.app_secret_plain}
          serverUrl={serverUrl}
          onAck={() => setRegenerated(null)}
        />
      )}
    </div>
  );
}
