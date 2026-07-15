"use client";
import { Popover, Tag } from "antd";
import { BookOutlined } from "@ant-design/icons";
import type { Agent } from "@/types/api";

export function AgentKBBadge({ agent }: { agent: Agent }) {
  const kbs = agent.knowledge_bases ?? [];
  if (kbs.length === 0) return null;

  const content = (
    <div style={{ maxWidth: 280 }}>
      {kbs.map((kb) => (
        <div key={kb.id} style={{ padding: "2px 0" }}>
          <span style={{ opacity: kb.status === "active" ? 1 : 0.6 }}>
            {kb.name}
          </span>
          {kb.status !== "active" && (
            <Tag color="default" style={{ marginLeft: 4, fontSize: 10 }}>
              {kb.status}
            </Tag>
          )}
        </div>
      ))}
    </div>
  );

  return (
    <Popover content={content} trigger="hover" placement="topRight">
      <Tag color="blue" style={{ cursor: "pointer" }}>
        <BookOutlined /> {kbs.length} 个知识库
      </Tag>
    </Popover>
  );
}
