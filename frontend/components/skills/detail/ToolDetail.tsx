"use client";
import { Tag, Descriptions, Alert } from "antd";
import { MarketplaceSkill } from "@/services/skills";

export function ToolDetail({ skill }: { skill: MarketplaceSkill }) {
  const cfg = (skill.type_config || {}) as {
    mcp_server?: string;
    tool_name?: string;
    param_schema?: Record<string, any>;
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
        <Descriptions.Item label="类型"><Tag color="cyan">工具</Tag></Descriptions.Item>
        <Descriptions.Item label="MCP Server">{cfg.mcp_server}</Descriptions.Item>
        <Descriptions.Item label="Tool Name">{cfg.tool_name}</Descriptions.Item>
        <Descriptions.Item label="下载">{skill.downloads}</Descriptions.Item>
      </Descriptions>
      {skill.description && (
        <div style={{ marginBottom: 16 }}>
          <h4 style={{ marginTop: 0, marginBottom: 8 }}>描述</h4>
          <p style={{ marginBottom: 0 }}>{skill.description}</p>
        </div>
      )}
      {cfg.param_schema && (
        <div style={{ marginBottom: 16 }}>
          <h4 style={{ marginTop: 0, marginBottom: 8 }}>参数 Schema</h4>
          <pre
            style={{
              background: "#f5f5f5", border: "1px solid #e8e8e8", borderRadius: 4,
              padding: 12, fontSize: 11, fontFamily: "Menlo, Consolas, monospace",
              whiteSpace: "pre-wrap", margin: 0,
            }}
          >
            {JSON.stringify(cfg.param_schema, null, 2)}
          </pre>
        </div>
      )}
      <Alert
        type="info"
        showIcon
        message="工具技能在 LLM 决定调用时执行 MCP 工具,结果回灌对话。"
      />
    </div>
  );
}
