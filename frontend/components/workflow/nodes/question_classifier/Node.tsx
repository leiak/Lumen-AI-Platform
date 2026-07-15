"use client";
import { Handle, Position } from "@xyflow/react";
import { Card, Tag } from "antd";

export function QuestionClassifierNode({ data, selected }: any) {
  const cats = (data?.config?.categories ?? []) as any[];
  return (
    <Card
      size="small"
      title={<><Tag color="volcano">QC</Tag> 问题分类</>}
      style={{ width: 200, borderColor: selected ? "#1890ff" : undefined }}
    >
      <Handle type="target" position={Position.Left} />
      <div style={{ fontSize: 12, color: "#595959" }}>
        {cats.length} 个类别
      </div>
      <Handle type="source" position={Position.Right} />
    </Card>
  );
}
