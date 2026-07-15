// frontend/components/workflow/nodes/parallel/Panel.tsx
import { Form, Input, Alert, Button, Space } from "antd";
import { PlusOutlined, DeleteOutlined } from "@ant-design/icons";
import { useState } from "react";
import type { PanelProps } from "../registry";

interface Branch {
  id: string;
  name: string;
  nodes?: unknown[];
  edges?: unknown[];
}

export function ParallelPanel({ node, onChange }: PanelProps) {
  const cfg = node.config ?? {};
  const parallel = cfg.parallel ?? { branches: [] };
  const branches: Branch[] = parallel.branches ?? [];

  const update = (next: Branch[]) =>
    onChange({ ...node, config: { ...cfg, parallel: { ...parallel, branches: next } } });

  return (
    <Form layout="vertical">
      <Form.Item label="节点名称">
        <Input
          value={cfg.title ?? ""}
          onChange={(e) => onChange({ ...node, config: { ...cfg, title: e.target.value } })}
        />
      </Form.Item>
      <Alert
        type="info"
        showIcon
        message="P1 范围:Parallel 接受 JSON 字符串描述的子图,P3 会升级为子图编辑器。"
        style={{ marginBottom: 12 }}
      />
      <Form.Item label="分支列表" required>
        {branches.map((b, i) => (
          <Space.Compact key={i} style={{ width: "100%", marginBottom: 4 }}>
            <Input
              value={b.name}
              placeholder="分支名称"
              onChange={(e) =>
                update(branches.map((x, j) => (i === j ? { ...x, name: e.target.value } : x)))
              }
            />
            <Button
              type="text"
              icon={<DeleteOutlined />}
              onClick={() => update(branches.filter((_, j) => j !== i))}
            />
          </Space.Compact>
        ))}
        <Button
          type="dashed"
          block
          icon={<PlusOutlined />}
          onClick={() =>
            update([...branches, { id: `b${branches.length + 1}`, name: `branch_${branches.length + 1}` }])
          }
        >
          添加分支
        </Button>
      </Form.Item>
    </Form>
  );
}
