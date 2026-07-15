"use client";
import { Form, Input, InputNumber, Table, Button } from "antd";
import { AdvancedOptions } from "../../_base/error/AdvancedOptions";
import { ModelSelector } from "../../ModelSelector";
import type { PanelProps } from "../registry";
import { nodeData } from "../registry";

export function QuestionClassifierPanel({ node, nodes, edges, onChange }: PanelProps) {
  const cfg = nodeData(node) as any;
  const update = (patch: Record<string, unknown>) =>
    onChange({ ...node, config: { ...cfg, ...patch } });

  const cats = (cfg.categories ?? []) as any[];

  const addRow = () =>
    update({ categories: [...cats, { id: "", name: "", description: "" }] });
  const updateRow = (i: number, p: any) => {
    const next = [...cats];
    next[i] = { ...next[i], ...p };
    update({ categories: next });
  };
  const removeRow = (i: number) =>
    update({ categories: cats.filter((_, j) => j !== i) });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Form.Item label="Model">
        <ModelSelector
          value={{
            model_config_id: cfg.model_config_id ?? null,
            model_name: cfg.model_name_cache ?? "",
          }}
          onChange={(v) =>
            update({
              model_config_id: v.model_config_id,
              model_name_cache: v.model_name,
            })
          }
        />
      </Form.Item>
      <Form.Item label="input_text">
        <Input.TextArea
          rows={3}
          value={cfg.input_text ?? ""}
          onChange={(e) => update({ input_text: e.target.value })}
        />
      </Form.Item>
      <div>
        <Button onClick={addRow} type="dashed" block>
          + 添加类别
        </Button>
        <Table
          size="small"
          style={{ marginTop: 8 }}
          dataSource={cats.map((c, i) => ({ ...c, _i: i }))}
          rowKey="_i"
          columns={[
            {
              title: "id",
              render: (_, r) => (
                <Input
                  value={r.id}
                  onChange={(e) => updateRow(r._i, { id: e.target.value })}
                />
              ),
            },
            {
              title: "name",
              render: (_, r) => (
                <Input
                  value={r.name}
                  onChange={(e) => updateRow(r._i, { name: e.target.value })}
                />
              ),
            },
            {
              title: "desc",
              render: (_, r) => (
                <Input
                  value={r.description}
                  onChange={(e) => updateRow(r._i, { description: e.target.value })}
                />
              ),
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
      </div>
      <Form.Item label="instruction">
        <Input.TextArea
          rows={2}
          value={cfg.instruction ?? ""}
          onChange={(e) => update({ instruction: e.target.value })}
        />
      </Form.Item>
      <Form.Item label="temperature">
        <InputNumber
          min={0}
          max={2}
          step={0.1}
          value={cfg.temperature ?? 0}
          onChange={(v) => update({ temperature: v })}
        />
      </Form.Item>
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
