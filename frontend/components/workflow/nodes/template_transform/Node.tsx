"use client";
import { Handle, Position } from "@xyflow/react";
import { Card, Tag } from "antd";

export function TemplateTransformNode({ data, selected }: any) {
  const tpl = data?.config?.template ?? "";
  return (
    <Card
      size="small"
      title={<><Tag color="magenta">Tpl</Tag> 模板转换</>}
      style={{
        width: 200,
        borderColor: selected ? "#1890ff" : undefined,
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
          fontFamily: "monospace",
        }}
      >
        {tpl.split("\n")[0] || "(空模板)"}
      </div>
      <Handle type="source" position={Position.Right} />
    </Card>
  );
}
