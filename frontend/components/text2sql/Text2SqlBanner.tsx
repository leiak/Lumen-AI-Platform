// frontend/components/text2sql/Text2SqlBanner.tsx
// M33 — sticky banner that surfaces the text2sql skill is enabled
// in the chat path (T31).
//
// Mirrors the M21 AgentKBBanner UX (sticky banner above the chat
// input, dismissable per-session) but with a much smaller surface
// area: text2sql is a single tool, no per-KB list. The banner is
// just a one-line reminder that "智能问数 已启用" so the user knows
// the LLM can call it.
"use client";
import { Tag, Button, Tooltip } from "antd";
import { CloseOutlined, DatabaseOutlined } from "@ant-design/icons";

export type Text2SqlBannerProps = {
  dataSourceName?: string;
  onClose?: () => void;
};

export function Text2SqlBanner({ dataSourceName, onClose }: Text2SqlBannerProps) {
  return (
    <div
      style={{
        padding: "8px 16px",
        background: "#f6ffed",
        borderBottom: "1px solid #b7eb8f",
        display: "flex",
        alignItems: "center",
        gap: 8,
        flexWrap: "wrap",
      }}
    >
      <DatabaseOutlined style={{ color: "#52c41a" }} />
      <span style={{ color: "#389e0d" }}>已启用智能问数:</span>
      <Tag color="green">
        {dataSourceName || "默认 ai_platform"}
      </Tag>
      <span style={{ color: "#389e0d", fontSize: 12 }}>
        业务问题里直接问「客户总数」「近 7 天新增」,系统会自动查库。
      </span>
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
