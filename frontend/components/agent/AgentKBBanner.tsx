"use client";
import { Tag, Button, Tooltip } from "antd";
import { CloseOutlined, BookOutlined } from "@ant-design/icons";
import type { Agent } from "@/types/api";

export type AgentKBBannerProps = {
  agent: Pick<Agent, "knowledge_bases">;
  onClose?: () => void;
};

export function AgentKBBanner({ agent, onClose }: AgentKBBannerProps) {
  const kbs = agent.knowledge_bases ?? [];
  if (kbs.length === 0) return null;

  return (
    <div
      style={{
        padding: "8px 16px",
        background: "#f0f5ff",
        borderBottom: "1px solid #d6e4ff",
        display: "flex",
        alignItems: "center",
        gap: 8,
        flexWrap: "wrap",
      }}
    >
      <BookOutlined style={{ color: "#1677ff" }} />
      <span style={{ color: "#1677ff" }}>已加载知识库:</span>
      {kbs.map((kb) => {
        const color = kb.status === "active" ? "blue" : "default";
        const style = kb.status !== "active" ? { opacity: 0.6 } : undefined;
        let text: React.ReactNode = kb.name;
        if (kb.status === "inactive") text = `${kb.name} (inactive)`;
        if (kb.status === "deleted") text = `⚠️ (已删除) ${kb.name}`;
        return (
          <Tag key={kb.id} color={color} style={style}>
            {text}
          </Tag>
        );
      })}
      {onClose && (
        <Tooltip title="本对话不再显示此提示">
          <Button
            type="text"
            size="small"
            icon={<CloseOutlined />}
            onClick={onClose}
            style={{ marginLeft: "auto" }}
          />
        </Tooltip>
      )}
    </div>
  );
}
