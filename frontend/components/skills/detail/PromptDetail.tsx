"use client";
import { Tag, Button, Rate, Descriptions, App } from "antd";
import { CopyOutlined } from "@ant-design/icons";
import { MarketplaceSkill } from "@/services/skills";

export function PromptDetail({ skill }: { skill: MarketplaceSkill }) {
  const { message } = App.useApp();
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
        <Descriptions.Item label="分类"><Tag>{skill.category}</Tag></Descriptions.Item>
        <Descriptions.Item label="评分">
          <Rate disabled allowHalf defaultValue={parseFloat(String(skill.rating ?? "0"))} />
          <span style={{ marginLeft: 8, color: "#666" }}>{skill.rating}</span>
        </Descriptions.Item>
        <Descriptions.Item label="下载次数">{skill.downloads}</Descriptions.Item>
        <Descriptions.Item label="认证状态">
          {skill.is_verified ? "✓ 已认证" : "未认证"}
        </Descriptions.Item>
      </Descriptions>
      {skill.description && (
        <div style={{ marginBottom: 16 }}>
          <h4 style={{ marginTop: 0, marginBottom: 8 }}>描述</h4>
          <p style={{ marginBottom: 0 }}>{skill.description}</p>
        </div>
      )}
      {skill.content && (
        <div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <h4 style={{ margin: 0 }}>Prompt 内容</h4>
            <Button
              type="link" size="small" icon={<CopyOutlined />}
              onClick={() => {
                try {
                  navigator.clipboard.writeText(skill.content!);
                  message.success("已复制到剪贴板");
                } catch (err) {
                  message.error("复制失败,请手动选择");
                }
              }}
            >
              复制
            </Button>
          </div>
          <pre
            style={{
              background: "#f5f5f5", border: "1px solid #e8e8e8", borderRadius: 4,
              padding: 12, maxHeight: 320, overflow: "auto", fontSize: 12,
              fontFamily: "Menlo, Consolas, monospace",
              whiteSpace: "pre-wrap", wordBreak: "break-word", margin: 0,
            }}
          >
            {skill.content}
          </pre>
        </div>
      )}
    </div>
  );
}
