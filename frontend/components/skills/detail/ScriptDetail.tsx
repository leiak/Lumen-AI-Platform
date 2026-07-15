"use client";
import { Tag, Descriptions, Alert } from "antd";
import { MarketplaceSkill } from "@/services/skills";

export function ScriptDetail({ skill }: { skill: MarketplaceSkill }) {
  const cfg = (skill.type_config || {}) as {
    code?: string;
    runtime?: string;
    timeout?: number;
    input_schema?: Record<string, any>;
    output_schema?: Record<string, any>;
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
        <Descriptions.Item label="类型"><Tag color="green">脚本</Tag></Descriptions.Item>
        <Descriptions.Item label="运行时">{cfg.runtime || "python-3.11"}</Descriptions.Item>
        <Descriptions.Item label="超时">{cfg.timeout ?? 30}s</Descriptions.Item>
        <Descriptions.Item label="下载">{skill.downloads}</Descriptions.Item>
      </Descriptions>
      {skill.description && (
        <div style={{ marginBottom: 16 }}>
          <h4 style={{ marginTop: 0, marginBottom: 8 }}>描述</h4>
          <p style={{ marginBottom: 0 }}>{skill.description}</p>
        </div>
      )}
      <h4 style={{ marginTop: 0, marginBottom: 8 }}>代码</h4>
      <pre
        style={{
          background: "#1e1e1e", color: "#d4d4d4", borderRadius: 4,
          padding: 12, maxHeight: 400, overflow: "auto", fontSize: 12,
          fontFamily: "Menlo, Consolas, monospace",
          whiteSpace: "pre", margin: 0,
        }}
      >
        {cfg.code || "(无代码)"}
      </pre>
      {(cfg.input_schema || cfg.output_schema) && (
        <div style={{ marginTop: 16 }}>
          <h4 style={{ marginTop: 0, marginBottom: 8 }}>接口定义</h4>
          {cfg.input_schema && (
            <div style={{ marginBottom: 8 }}>
              <strong>输入:</strong>
              <pre
                style={{
                  background: "#f5f5f5", border: "1px solid #e8e8e8", borderRadius: 4,
                  padding: 8, fontSize: 11, fontFamily: "Menlo, Consolas, monospace",
                  whiteSpace: "pre-wrap", marginTop: 4,
                }}
              >
                {JSON.stringify(cfg.input_schema, null, 2)}
              </pre>
            </div>
          )}
          {cfg.output_schema && (
            <div>
              <strong>输出:</strong>
              <pre
                style={{
                  background: "#f5f5f5", border: "1px solid #e8e8e8", borderRadius: 4,
                  padding: 8, fontSize: 11, fontFamily: "Menlo, Consolas, monospace",
                  whiteSpace: "pre-wrap", marginTop: 4,
                }}
              >
                {JSON.stringify(cfg.output_schema, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
      <Alert
        type="info"
        showIcon
        style={{ marginTop: 16 }}
        message="脚本技能在 LLM 决定调用时执行,结果回灌对话。"
      />
    </div>
  );
}
