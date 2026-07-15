// frontend/components/workflow/nodes/fan_in/Panel.tsx
import { Form, Input, Select, Radio } from "antd";
import type { PanelProps } from "../registry";

export function FanInPanel({ node, nodes, onChange }: PanelProps) {
  const cfg = node.config ?? {};
  const fanIn = cfg.fan_in ?? { source: null, aggregation: "collect" };
  return (
    <Form layout="vertical">
      <Form.Item label="节点名称">
        <Input
          value={cfg.title ?? ""}
          onChange={(e) => onChange({ ...node, config: { ...cfg, title: e.target.value } })}
        />
      </Form.Item>
      <Form.Item label="上游节点 (Fan-Out 节点)" required>
        <Select
          value={fanIn.source}
          placeholder="选择 Fan-Out 节点"
          style={{ width: "100%" }}
          onChange={(v) => onChange({ ...node, config: { ...cfg, fan_in: { ...fanIn, source: v } } })}
          options={nodes
            .filter((n) => n.type === "fan_out")
            .map((n) => ({ value: n.id, label: n.config?.title ?? n.id }))}
        />
      </Form.Item>
      <Form.Item label="聚合方式">
        <Radio.Group
          value={fanIn.aggregation}
          onChange={(e) =>
            onChange({ ...node, config: { ...cfg, fan_in: { ...fanIn, aggregation: e.target.value } } })
          }
        >
          <Radio.Button value="collect">collect</Radio.Button>
          <Radio.Button value="sum">sum</Radio.Button>
          <Radio.Button value="average">average</Radio.Button>
        </Radio.Group>
      </Form.Item>
    </Form>
  );
}
