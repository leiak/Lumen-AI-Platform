// frontend/components/workflow/_base/condition/ConditionCaseEditor.tsx
import { Button, Card, Radio, Space } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useState } from "react";
import type { WorkflowNode, WorkflowEdge } from "@/services/workflow";
import { ConditionRow, ConditionRowValue } from "./ConditionRow";

export interface ConditionCase {
  case_id: string;
  logical_operator: "and" | "or";
  conditions: ConditionRowValue[];
}

function genId() {
  return Math.random().toString(36).slice(2, 10);
}

export function ConditionCaseEditor({
  nodeId,
  nodes,
  edges,
  cases,
  onChange,
}: {
  nodeId: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  cases: ConditionCase[];
  onChange: (cases: ConditionCase[]) => void;
}) {
  const updateCase = (idx: number, patch: Partial<ConditionCase>) => {
    onChange(cases.map((c, i) => (i === idx ? { ...c, ...patch } : c)));
  };
  const addCase = () => {
    onChange([
      ...cases,
      { case_id: genId(), logical_operator: "and", conditions: [] },
    ]);
  };
  const removeCase = (idx: number) => onChange(cases.filter((_, i) => i !== idx));
  const addCondition = (idx: number) => {
    updateCase(idx, {
      conditions: [
        ...cases[idx].conditions,
        { variable_selector: [], comparison_operator: "=", value: "" },
      ],
    });
  };
  const updateCondition = (ci: number, idx: number, v: ConditionRowValue) => {
    const next = cases[ci].conditions.map((c, i) => (i === idx ? v : c));
    updateCase(ci, { conditions: next });
  };
  const removeCondition = (ci: number, idx: number) => {
    updateCase(ci, { conditions: cases[ci].conditions.filter((_, i) => i !== idx) });
  };

  return (
    <div>
      {cases.map((c, ci) => (
        <Card
          key={c.case_id}
          size="small"
          title={`Case ${ci + 1} (id: ${c.case_id})`}
          extra={
            <Button size="small" type="text" danger onClick={() => removeCase(ci)}>
              删除
            </Button>
          }
          style={{ marginBottom: 8 }}
        >
          <Radio.Group
            value={c.logical_operator}
            onChange={(e) => updateCase(ci, { logical_operator: e.target.value })}
            style={{ marginBottom: 8 }}
          >
            <Radio.Button value="and">AND</Radio.Button>
            <Radio.Button value="or">OR</Radio.Button>
          </Radio.Group>
          {c.conditions.map((cond, idx) => (
            <div key={idx} style={{ marginBottom: 4 }}>
              <ConditionRow
                nodeId={nodeId}
                nodes={nodes}
                edges={edges}
                value={cond}
                onChange={(v) => updateCondition(ci, idx, v)}
                onRemove={() => removeCondition(ci, idx)}
              />
            </div>
          ))}
          <Button
            type="dashed"
            size="small"
            icon={<PlusOutlined />}
            onClick={() => addCondition(ci)}
            block
          >
            添加条件
          </Button>
        </Card>
      ))}
      <Button type="dashed" block icon={<PlusOutlined />} onClick={addCase}>
        添加 Case (ELIF)
      </Button>
    </div>
  );
}
