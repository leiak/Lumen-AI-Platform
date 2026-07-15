// frontend/components/workflow/_base/condition/ConditionRow.tsx
import { Input, Select, Button, Space } from "antd";
import { DeleteOutlined } from "@ant-design/icons";
import { VarReferencePicker } from "../variable/VarReferencePicker";
import type { WorkflowNode, WorkflowEdge } from "@/services/workflow";

const OPERATORS = [
  "=",
  "!=",
  "contains",
  "not contains",
  ">",
  "<",
  ">=",
  "<=",
  "starts_with",
  "ends_with",
  "exists",
  "empty",
];

export interface ConditionRowValue {
  variable_selector: string[];
  comparison_operator: string;
  value?: string | number | boolean;
}

export function ConditionRow({
  nodeId,
  nodes,
  edges,
  value,
  onChange,
  onRemove,
}: {
  nodeId: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  value: ConditionRowValue;
  onChange: (v: ConditionRowValue) => void;
  onRemove: () => void;
}) {
  const isExistence = value.comparison_operator === "exists" || value.comparison_operator === "empty";
  return (
    <Space.Compact style={{ width: "100%", display: "flex", gap: 4 }}>
      <div style={{ flex: 1, minWidth: 200 }}>
        <VarReferencePicker
          nodeId={nodeId}
          nodes={nodes}
          edges={edges}
          value={value.variable_selector.length ? value.variable_selector : null}
          onChange={(selector) =>
            onChange({ ...value, variable_selector: selector })
          }
          placeholder="选择变量"
        />
      </div>
      <Select
        value={value.comparison_operator}
        style={{ width: 130 }}
        onChange={(v) => onChange({ ...value, comparison_operator: v })}
        options={OPERATORS.map((op) => ({ value: op, label: op }))}
      />
      <Input
        value={String(value.value ?? "")}
        disabled={isExistence}
        onChange={(e) => onChange({ ...value, value: e.target.value })}
        style={{ width: 120 }}
        placeholder="值"
      />
      <Button icon={<DeleteOutlined />} type="text" onClick={onRemove} />
    </Space.Compact>
  );
}
