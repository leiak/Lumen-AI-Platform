// frontend/components/workflow/nodes/agent/Panel.tsx
import { Form, Input, Select, Spin, Alert } from "antd";
import { useEffect, useState } from "react";
import { agentApi } from "@/services/agent";
import type { PanelProps } from "../registry";

interface Agent {
  id: number;
  name: string;
  description?: string;
}

export function AgentPanel({ node, onChange }: PanelProps) {
  const cfg = node.config ?? {};
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    agentApi
      .list(1, 100)
      .then((res: any) => {
        if (cancelled) return;
        // PaginatedResponse 信封:res.data = 信封 {code,data,total,...},
        // res.data.data 才是数组(CLAUDE.md §2 契约,跟 lumen_schemas.common.PaginatedResponse 一致)
        const items = res?.data?.data ?? res?.data ?? [];
        setAgents(Array.isArray(items) ? items : []);
      })
      .catch((e: any) => !cancelled && setError(String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Form layout="vertical">
      <Form.Item label="节点名称">
        <Input
          value={cfg.title ?? ""}
          onChange={(e) => onChange({ ...node, config: { ...cfg, title: e.target.value } })}
        />
      </Form.Item>
      <Form.Item label="选择 Agent" required>
        {error && <Alert type="error" message={error} style={{ marginBottom: 8 }} />}
        {loading ? (
          <Spin />
        ) : (
          <Select
            value={cfg.agent_id}
            placeholder="选择一个 Agent"
            style={{ width: "100%" }}
            onChange={(v) => onChange({ ...node, config: { ...cfg, agent_id: v } })}
            options={agents.map((a) => ({
              value: a.id,
              label: a.name,
            }))}
            showSearch
            optionFilterProp="label"
          />
        )}
      </Form.Item>
    </Form>
  );
}
