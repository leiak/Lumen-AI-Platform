"use client";
import { Handle, Position } from "@xyflow/react";
import { Card, Tag } from "antd";

export function VariableAggregatorNode({ data, selected }: any) {
  const agg = data?.config?.aggregation ?? "collect";
  return (
    <Card
      size="small"
      title={<><Tag color="lime">Vagg</Tag> 变量聚合</>}
      style={{ width: 200, borderColor: selected ? "#1890ff" : undefined }}
    >
      <Handle type="target" position={Position.Left} />
      <div style={{ fontSize: 12, color: "#595959" }}>aggregation: {agg}</div>
      <Handle type="source" position={Position.Right} />
    </Card>
  );
}
