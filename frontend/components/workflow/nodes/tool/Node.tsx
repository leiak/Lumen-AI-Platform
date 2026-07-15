"use client";
import { Handle, Position } from "@xyflow/react";
import { Card, Tag } from "antd";

interface NodeProps {
  data?: { config?: { tool_name_cache?: string; tool_id?: number } };
  selected?: boolean;
}

export function ToolNode({ data, selected }: NodeProps) {
  const name = data?.config?.tool_name_cache ?? "(未选择)";
  return (
    <Card
      size="small"
      title={
        <span>
          <Tag color="cyan">Tool</Tag> MCP 工具
        </span>
      }
      style={{
        width: 200,
        borderColor: selected ? "#1677ff" : undefined,
        borderWidth: selected ? 2 : 1,
      }}
    >
      <Handle type="target" position={Position.Left} />
      <div
        style={{
          fontSize: 12,
          color: "#595959",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {name}
      </div>
      <Handle type="source" position={Position.Right} />
    </Card>
  );
}
