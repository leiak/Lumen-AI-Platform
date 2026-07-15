"use client";
import { Handle, Position } from "@xyflow/react";
import { Card } from "antd";

interface NodeProps {
  data?: { config?: { code?: string } };
  selected?: boolean;
}

export function CodeNode({ data, selected }: NodeProps) {
  const firstLine = data?.config?.code ? data.config.code.split("\n")[0] : "(无代码)";
  return (
    <Card
      size="small"
      title="Python 代码"
      style={{
        width: 200,
        borderColor: selected ? "#1677ff" : undefined,
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
        {firstLine}
      </div>
      <Handle type="source" position={Position.Right} />
    </Card>
  );
}
