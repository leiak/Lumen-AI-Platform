// frontend/components/workflow/nodes/input/Panel.tsx
import { Form, Input } from "antd";
import { VarList } from "./VarList";
import { InputVariable } from "./types";
import { VarType } from "@/components/workflow/_base/variable/types";
import type { PanelProps } from "../registry";

export function InputPanel({ node, onChange }: PanelProps) {
  const cfg = node.config ?? {};
  const variables: InputVariable[] =
    cfg.variables ?? [{ name: "value", type: VarType.object, required: false }];

  return (
    <Form layout="vertical">
      <Form.Item label="节点名称">
        <Input
          value={cfg.title ?? ""}
          onChange={(e) => onChange({ ...node, config: { ...cfg, title: e.target.value } })}
        />
      </Form.Item>
      <Form.Item label="输入变量">
        <VarList
          value={variables}
          onChange={(v) => onChange({ ...node, config: { ...cfg, variables: v } })}
        />
      </Form.Item>
    </Form>
  );
}
