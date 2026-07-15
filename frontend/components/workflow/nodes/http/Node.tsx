"use client";
import { Handle, Position } from "@xyflow/react";
import { Card, Tag } from "antd";

interface NodeProps {
  data?: { config?: { method?: string; url?: string } };
  selected?: boolean;
}

const METHOD_COLOR: Record<string, string> = {
  GET: "blue",
  POST: "green",
  PUT: "orange",
  PATCH: "purple",
  DELETE: "red",
};

export function HTTPNode({ data, selected }: NodeProps) {
  const method = data?.config?.method ?? "GET";
  const color = METHOD_COLOR[method] ?? "default";
  return (
    <Card
      size="small"
      title={
        <span>
          <Tag color={color}>{method}</Tag> HTTP 请求
        </span>
      }
      style={{
        width: 220,
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
        {data?.config?.url ?? "(无 URL)"}
      </div>
      <Handle type="source" position={Position.Right} />
    </Card>
  );
}
