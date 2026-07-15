"use client";
import { Handle, Position } from "@xyflow/react";
import { Card, Tag } from "antd";

export function VariableAssignerNode({ data, selected }: any) {
  const ops = (data?.config?.operations ?? []) as any[];
  return (
    <Card
      size="small"
      title={
        <>
          <Tag color="geekblue">VA</Tag> 变量赋值
        </>
      }
      style={{ width: 200, borderColor: selected ? "#1890ff" : undefined }}
    >
      <Handle type="target" position={Position.Left} />
      <div style={{ fontSize: 12, color: "#595959" }}>
        {ops.length} 个操作
      </div>
      <Handle type="source" position={Position.Right} />
    </Card>
  );
}
