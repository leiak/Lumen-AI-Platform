"use client";
import { Tag, Descriptions, Alert } from "antd";
import { MarketplaceSkill } from "@/services/skills";

export function HttpDetail({ skill }: { skill: MarketplaceSkill }) {
  const cfg = (skill.type_config || {}) as {
    url?: string;
    method?: string;
    headers?: Record<string, string>;
    body_template?: string;
    timeout?: number;
    auth?: { type: string; credential_ref: string };
  };
  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h3 style={{ margin: 0, marginBottom: 4 }}>
          {skill.name}
          {skill.version && (
            <Tag color="blue" style={{ marginLeft: 8, verticalAlign: "middle" }}>
              v{skill.version}
            </Tag>
          )}
          {skill.is_verified && (
            <Tag color="green" style={{ marginLeft: 4, verticalAlign: "middle" }}>
              ✓ 已认证
            </Tag>
          )}
        </h3>
        {skill.provider && (
          <span style={{ color: "#666", fontSize: 13 }}>提供方: {skill.provider}</span>
        )}
      </div>
      <Descriptions column={2} size="small" bordered style={{ marginBottom: 16 }}>
        <Descriptions.Item label="类型"><Tag color="orange">API</Tag></Descriptions.Item>
        <Descriptions.Item label="方法">
          <Tag color={cfg.method === "GET" ? "blue" : "purple"}>{cfg.method || "GET"}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="超时">{cfg.timeout ?? 30}s</Descriptions.Item>
        <Descriptions.Item label="下载">{skill.downloads}</Descriptions.Item>
        <Descriptions.Item label="URL" span={2}>
          <code style={{ fontSize: 12, wordBreak: "break-all" }}>{cfg.url || "(未配置)"}</code>
        </Descriptions.Item>
      </Descriptions>
      {skill.description && (
        <div style={{ marginBottom: 16 }}>
          <h4 style={{ marginTop: 0, marginBottom: 8 }}>描述</h4>
          <p style={{ marginBottom: 0 }}>{skill.description}</p>
        </div>
      )}
      {cfg.headers && Object.keys(cfg.headers).length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <h4 style={{ marginTop: 0, marginBottom: 8 }}>Headers</h4>
          <Descriptions column={1} size="small" bordered>
            {Object.entries(cfg.headers).map(([k, v]) => (
              <Descriptions.Item key={k} label={k}>
                <code style={{ fontSize: 12 }}>{v}</code>
              </Descriptions.Item>
            ))}
          </Descriptions>
        </div>
      )}
      {cfg.body_template && (
        <div style={{ marginBottom: 16 }}>
          <h4 style={{ marginTop: 0, marginBottom: 8 }}>Body 模板</h4>
          <pre
            style={{
              background: "#f5f5f5", border: "1px solid #e8e8e8", borderRadius: 4,
              padding: 12, fontSize: 12, fontFamily: "Menlo, Consolas, monospace",
              whiteSpace: "pre-wrap", margin: 0,
            }}
          >
            {cfg.body_template}
          </pre>
        </div>
      )}
      {cfg.auth && (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 16 }}
          message={`认证方式: ${cfg.auth.type} (凭据在 .env 中管理,引用: ${cfg.auth.credential_ref})`}
          description="平台不会显示真实凭据值,只在调用时通过 ${ENV_VAR} 引用。"
        />
      )}
    </div>
  );
}
