"use client";
import { Alert, Form, Input, Select, Table, Button } from "antd";
import { useState } from "react";
import { AdvancedOptions } from "../../_base/error/AdvancedOptions";
import { useAvailableVarList } from "../../_base/hooks/useAvailableVarList";
import { VarReferencePopup } from "../../_base/variable/VarReferencePopup";
import type { PanelProps } from "../registry";
import { nodeData } from "../registry";

export function VariableAssignerPanel({ node, nodes, edges, onChange }: PanelProps) {
  const cfg = nodeData(node) as any;
  const update = (patch: Record<string, unknown>) =>
    onChange({ ...node, config: { ...cfg, ...patch } });

  const ops = (cfg.operations ?? []) as any[];
  const allVars = useAvailableVarList(node.id ?? "", nodes, edges);
  // Track which row's popup is open (for click-to-open behavior)
  const [openRowIdx, setOpenRowIdx] = useState<number | null>(null);

  const addRow = () =>
    update({
      operations: [
        ...ops,
        {
          variable: "",
          value_source: "constant",
          constant_value: "",
          upstream_ref: [],
          expression: "",
        },
      ],
    });
  const updateRow = (i: number, p: any) => {
    const next = [...ops];
    next[i] = { ...next[i], ...p };
    update({ operations: next });
  };
  const removeRow = (i: number) =>
    update({ operations: ops.filter((_, j) => j !== i) });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Alert
        type="info"
        showIcon
        message="每个 operation 写入位置:[node_id, variable]"
      />
      <Button onClick={addRow} type="dashed" block>
        + 添加赋值
      </Button>
      <Table
        size="small"
        dataSource={ops.map((o, i) => ({ ...o, _i: i }))}
        rowKey="_i"
        columns={[
          {
            title: "变量名",
            render: (_, r) => (
              <Input
                value={r.variable}
                onChange={(e) => updateRow(r._i, { variable: e.target.value })}
              />
            ),
          },
          {
            title: "来源",
            render: (_, r) => (
              <Select
                value={r.value_source}
                onChange={(v) => updateRow(r._i, { value_source: v })}
                options={[
                  { value: "constant", label: "常量" },
                  { value: "upstream_ref", label: "上游引用" },
                  { value: "expression", label: "Jinja2 表达式" },
                ]}
              />
            ),
          },
          {
            title: "值",
            render: (_, r) => {
              if (r.value_source === "constant") {
                return (
                  <Input.TextArea
                    rows={1}
                    value={String(r.constant_value ?? "")}
                    onChange={(e) =>
                      updateRow(r._i, { constant_value: e.target.value })
                    }
                  />
                );
              }
              if (r.value_source === "upstream_ref") {
                const ref = r.upstream_ref ?? [];
                const display =
                  Array.isArray(ref) && ref.length === 2
                    ? `${ref[0]}.${ref[1]}`
                    : "(未选择)";
                return (
                  <VarReferencePopup
                    open={openRowIdx === r._i}
                    onOpenChange={(o) => setOpenRowIdx(o ? r._i : null)}
                    vars={allVars}
                    onPick={(v) =>
                      updateRow(r._i, {
                        upstream_ref: [v.nodeId, v.variable],
                      })
                    }
                  >
                    <Button size="small" block>
                      {display}
                    </Button>
                  </VarReferencePopup>
                );
              }
              return (
                <Input
                  value={r.expression ?? ""}
                  placeholder="Jinja2 表达式"
                  onChange={(e) =>
                    updateRow(r._i, { expression: e.target.value })
                  }
                />
              );
            },
          },
          {
            title: "",
            render: (_, r) => (
              <Button danger size="small" onClick={() => removeRow(r._i)}>
                删
              </Button>
            ),
          },
        ]}
        pagination={false}
      />
      <AdvancedOptions
        config={{
          error_strategy: (cfg.error_strategy ?? null) as any,
          default_value: cfg.default_value ?? null,
          retry_config: cfg.retry_config ?? null,
          timeout: cfg.timeout ?? null,
        }}
        onChange={(patch) => update(patch)}
      />
    </div>
  );
}
