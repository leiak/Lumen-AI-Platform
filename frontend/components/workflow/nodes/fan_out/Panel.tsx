// frontend/components/workflow/nodes/fan_out/Panel.tsx
import { Form, Input, Select, Alert } from "antd";
import { useEffect, useState } from "react";
import { workflowApi } from "@/services/workflow";
import type { PanelProps } from "../registry";

export function FanOutPanel({ node, onChange }: PanelProps) {
  const cfg = node.config ?? {};
  const fanOut = cfg.fan_out ?? { items: [], sub_workflow: null };
  const [workflows, setWorkflows] = useState<any[]>([]);

  useEffect(() => {
    workflowApi
      .list(1, 100)
      .then((res: any) => {
        const items = res?.data?.data?.items ?? res?.data?.items ?? [];
        setWorkflows(items);
      })
      .catch(() => setWorkflows([]));
  }, []);

  const update = (patch: any) =>
    onChange({ ...node, config: { ...cfg, fan_out: { ...fanOut, ...patch } } });

  return (
    <Form layout="vertical">
      <Form.Item label="节点名称">
        <Input
          value={cfg.title ?? ""}
          onChange={(e) => onChange({ ...node, config: { ...cfg, title: e.target.value } })}
        />
      </Form.Item>
      <Form.Item label="Items (换行或逗号分隔)">
        <Input.TextArea
          rows={3}
          value={(fanOut.items ?? []).join("\n")}
          onChange={(e) =>
            update({ items: e.target.value.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean) })
          }
        />
      </Form.Item>
      <Form.Item label="Sub-workflow (P3 接入)">
        <Select
          allowClear
          value={fanOut.sub_workflow}
          placeholder="(P1 stub: 不执行子图)"
          style={{ width: "100%" }}
          onChange={(v) => update({ sub_workflow: v })}
          options={workflows.map((w) => ({ value: w.id, label: w.name }))}
        />
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 8 }}
          message="P1 stub: 仅按 items 拆分,sub_workflow 不执行。"
        />
      </Form.Item>
    </Form>
  );
}
