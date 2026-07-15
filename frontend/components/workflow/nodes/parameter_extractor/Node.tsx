"use client";
import { Handle, Position } from "@xyflow/react";
import { Card, Tag } from "antd";

export function ParameterExtractorNode({ data, selected }: any) {
  const params = (data?.config?.parameters ?? []) as any[];
  return (
    <Card
      size="small"
      title={<><Tag color="gold">PE</Tag> 参数抽取</>}
      style={{ width: 200, borderColor: selected ? "#1890ff" : undefined }}
    >
      <Handle type="target" position={Position.Left} />
      <div style={{ fontSize: 12, color: "#595959" }}>
        {params.length} 个参数
      </div>
      <Handle type="source" position={Position.Right} />
    </Card>
  );
}
