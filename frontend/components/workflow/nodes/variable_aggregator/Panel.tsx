"use client";
import { Form, Input, Radio, Select, Alert } from "antd";
import { AdvancedOptions } from "../../_base/error/AdvancedOptions";
import type { PanelProps } from "../registry";
import { nodeData } from "../registry";

const MULTI_OUTPUT_TYPES = new Set(["fan_out", "variable_assigner", "parallel"]);

export function VariableAggregatorPanel({ node, nodes, edges, onChange }: PanelProps) {
  const cfg = nodeData(node) as any;
  const update = (patch: Record<string, unknown>) =>
    onChange({ ...node, config: { ...cfg, ...patch } });

  const sourceNodes = nodes.filter((n) => MULTI_OUTPUT_TYPES.has(n.type));
  const sourceNode = sourceNodes.find((n) => n.id === cfg.source_node_id);
  const sourceVars = (sourceNode?.config?.outputs ?? []) as { name: string; type: string }[];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Alert type="info" showIcon message="聚合上游单一 list 类型的 var" />
      <Form.Item label="源节点(多输出)">
        <Select
          value={cfg.source_node_id ?? undefined}
          onChange={(v) => update({ source_node_id: v, source_var: "results" })}
          options={sourceNodes.map((n) => ({ value: n.id, label: n.id }))}
          placeholder="选择 Fan-out / VariableAssigner / Parallel"
        />
      </Form.Item>
      <Form.Item label="源变量">
        <Select
          value={cfg.source_var ?? "results"}
          onChange={(v) => update({ source_var: v })}
          options={sourceVars.length ? sourceVars.map((v) => ({ value: v.name, label: v.name })) : [{ value: "results", label: "results" }]}
        />
      </Form.Item>
      <Form.Item label="aggregation">
        <Radio.Group
          value={cfg.aggregation ?? "collect"}
          onChange={(e) => update({ aggregation: e.target.value })}
        >
          <Radio.Button value="collect">collect</Radio.Button>
          <Radio.Button value="sum">sum</Radio.Button>
          <Radio.Button value="average">average</Radio.Button>
          <Radio.Button value="join">join</Radio.Button>
          <Radio.Button value="first">first</Radio.Button>
          <Radio.Button value="last">last</Radio.Button>
        </Radio.Group>
      </Form.Item>
      {cfg.aggregation === "join" && (
        <Form.Item label="join_separator">
          <Input value={cfg.join_separator ?? "\n"} onChange={(e) => update({ join_separator: e.target.value })} />
        </Form.Item>
      )}
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
