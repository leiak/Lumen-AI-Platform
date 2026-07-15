// frontend/components/workflow/_base/variable/VarReferencePicker.tsx
import { Button, Input, Space } from "antd";
import { useState } from "react";
import { useAvailableVarList } from "../hooks/useAvailableVarList";
import type { ValueSelector, Var, VarType } from "./types";
import { VarReferencePopup } from "./VarReferencePopup";
import type { WorkflowNode, WorkflowEdge } from "@/services/workflow";

export interface VarReferencePickerProps {
  nodeId: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  value: ValueSelector | null;
  onChange: (selector: ValueSelector, varType: VarType) => void;
  filterVar?: (v: Var) => boolean;
  placeholder?: string;
  readOnly?: boolean;
}

export function VarReferencePicker({
  nodeId,
  nodes,
  edges,
  value,
  onChange,
  filterVar,
  placeholder = "选择变量",
  readOnly,
}: VarReferencePickerProps) {
  const [open, setOpen] = useState(false);
  const vars = useAvailableVarList(nodeId, nodes, edges, { filterVar });
  const display = value ? `{{ ${value.join(".")} }}` : "";

  return (
    <Space.Compact style={{ width: "100%" }}>
      <Input
        value={display}
        placeholder={placeholder}
        readOnly
        onClick={() => !readOnly && setOpen(true)}
        data-testid="var-picker-input"
      />
      <Button
        type="default"
        onClick={() => setOpen(true)}
        disabled={readOnly}
        data-testid="var-picker-button"
      >
        选择
      </Button>
      <VarReferencePopup
        open={open}
        onOpenChange={setOpen}
        vars={vars}
        onPick={(v) => {
          onChange([v.nodeId, v.variable], v.type);
          setOpen(false);
        }}
      >
        <span style={{ display: "none" }} />
      </VarReferencePopup>
    </Space.Compact>
  );
}
