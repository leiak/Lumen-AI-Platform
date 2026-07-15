import { Form, Input, Radio } from "antd";
import type { PanelProps } from "../registry";

export function OutputPanel({ node, onChange }: PanelProps) {
  const cfg = node.config ?? {};
  const field: string = cfg.field ?? "current";
  return (
    <Form layout="vertical">
      <Form.Item label="节点名称">
        <Input
          value={cfg.title ?? ""}
          onChange={(e) => onChange({ ...node, config: { ...cfg, title: e.target.value } })}
        />
      </Form.Item>
      <Form.Item label="输出字段" required>
        <Radio.Group
          value={["current", "input", "all"].includes(field) ? field : "custom"}
          onChange={(e) => onChange({ ...node, config: { ...cfg, field: e.target.value } })}
        >
          <Radio.Button value="current">current</Radio.Button>
          <Radio.Button value="input">input</Radio.Button>
          <Radio.Button value="all">all</Radio.Button>
          <Radio.Button value="custom">自定义</Radio.Button>
        </Radio.Group>
        {field === "custom" || !["current", "input", "all"].includes(field) ? (
          <Input
            value={field}
            placeholder="node_id.var_name"
            onChange={(e) => onChange({ ...node, config: { ...cfg, field: e.target.value } })}
            style={{ marginTop: 8 }}
          />
        ) : null}
      </Form.Item>
    </Form>
  );
}
