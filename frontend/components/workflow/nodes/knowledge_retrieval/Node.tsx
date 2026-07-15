"use client";
import { Handle, Position } from "@xyflow/react";
import { Card, Tag } from "antd";

interface NodeProps {
  data?: { config?: { kb_name_cache?: string } };
  selected?: boolean;
}

export function KBRetrievalNode({ data, selected }: NodeProps) {
  const name = data?.config?.kb_name_cache ?? "(未选择)";
  return (
    <Card
      size="small"
      title={
        <span>
          <Tag color="purple">KB</Tag> 知识库检索
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
        {name}
      </div>
      <Handle type="source" position={Position.Right} />
    </Card>
  );
}
