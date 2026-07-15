"use client";
import { Tag, Descriptions, Alert } from "antd";
import { MarketplaceSkill } from "@/services/skills";

export function KnowledgeRetrievalDetail({ skill }: { skill: MarketplaceSkill }) {
  const cfg = (skill.type_config || {}) as {
    kb_id?: number;
    top_k?: number;
    score_threshold?: number;
    query_template?: string;
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
        <Descriptions.Item label="类型"><Tag color="purple">知识库</Tag></Descriptions.Item>
        <Descriptions.Item label="KB ID">{cfg.kb_id}</Descriptions.Item>
        <Descriptions.Item label="Top K">{cfg.top_k ?? 5}</Descriptions.Item>
        <Descriptions.Item label="相似度阈值">{cfg.score_threshold ?? 0.7}</Descriptions.Item>
        <Descriptions.Item label="下载">{skill.downloads}</Descriptions.Item>
      </Descriptions>
      {skill.description && (
        <div style={{ marginBottom: 16 }}>
          <h4 style={{ marginTop: 0, marginBottom: 8 }}>描述</h4>
          <p style={{ marginBottom: 0 }}>{skill.description}</p>
        </div>
      )}
      {cfg.query_template && (
        <div style={{ marginBottom: 16 }}>
          <h4 style={{ marginTop: 0, marginBottom: 8 }}>查询模板</h4>
          <pre
            style={{
              background: "#f5f5f5", border: "1px solid #e8e8e8", borderRadius: 4,
              padding: 12, fontSize: 12, fontFamily: "Menlo, Consolas, monospace",
              whiteSpace: "pre-wrap", margin: 0,
            }}
          >
            {cfg.query_template}
          </pre>
        </div>
      )}
      <Alert
        type="info"
        showIcon
        message="知识库技能在 LLM 决定调用时检索,top-k chunks 作为 context 回灌。"
      />
    </div>
  );
}
