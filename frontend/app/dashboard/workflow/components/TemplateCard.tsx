"use client";

import { Card, Tag, Button, Space, Tooltip } from "antd";
import {
  EyeOutlined,
  DownloadOutlined,
  UserOutlined,
  StarOutlined,
} from "@ant-design/icons";
import type { WorkflowTemplate } from "@/services/workflowTemplate";

interface Props {
  template: WorkflowTemplate;
  onPreview: (id: number) => void;
  onImport: (id: number) => void;
}

/**
 * M30b: workflow template card. The marketplace-style layout fits
 * the 3-column grid in the templates page.
 */
export function TemplateCard({ template, onPreview, onImport }: Props) {
  return (
    <Card
      hoverable
      size="small"
      title={
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>{template.name}</span>
          <Tag color="blue">{template.category}</Tag>
        </div>
      }
      actions={[
        <Tooltip title="预览" key="preview">
          <Button
            type="text"
            icon={<EyeOutlined />}
            onClick={() => onPreview(template.id)}
          />
        </Tooltip>,
        <Tooltip title="导入到我的工作流" key="import">
          <Button
            type="text"
            icon={<DownloadOutlined />}
            onClick={() => onImport(template.id)}
          />
        </Tooltip>,
      ]}
    >
      <div
        style={{
          minHeight: 60,
          color: "#555",
          fontSize: 13,
          marginBottom: 12,
        }}
      >
        {template.description || "（无描述）"}
      </div>
      <Space wrap size={4}>
        {(template.tags || []).map((t) => (
          <Tag key={t}>{t}</Tag>
        ))}
      </Space>
      <div
        style={{
          marginTop: 12,
          fontSize: 12,
          color: "#888",
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>
          <UserOutlined /> {template.author_name || `用户 #${template.author_id}`}
        </span>
        <span>
          <StarOutlined /> {template.downloads} 次使用
        </span>
      </div>
    </Card>
  );
}
