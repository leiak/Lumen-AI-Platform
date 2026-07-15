// frontend/components/workflow/nodes/condition/Panel.tsx
import { Form, Input } from "antd";
import { ConditionCaseEditor, ConditionCase } from "@/components/workflow/_base/condition/ConditionCaseEditor";
import type { PanelProps } from "../registry";

function genId() {
  return Math.random().toString(36).slice(2, 10);
}

export function ConditionPanel({ node, nodes, edges, onChange }: PanelProps) {
  const cfg = node.config ?? {};
  const cases: ConditionCase[] = cfg.cases ?? [
    { case_id: genId(), logical_operator: "and", conditions: [] },
  ];
  return (
    <Form layout="vertical">
      <Form.Item label="节点名称">
        <Input
          value={cfg.title ?? ""}
          onChange={(e) => onChange({ ...node, config: { ...cfg, title: e.target.value } })}
        />
      </Form.Item>
      <Form.Item label="条件 Cases (依次匹配,首个 True 命中)">
        <ConditionCaseEditor
          nodeId={node.id}
          nodes={nodes}
          edges={edges}
          cases={cases}
          onChange={(c) => onChange({ ...node, config: { ...cfg, cases: c } })}
        />
      </Form.Item>
    </Form>
  );
}
