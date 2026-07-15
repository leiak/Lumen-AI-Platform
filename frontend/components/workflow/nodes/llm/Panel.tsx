// frontend/components/workflow/nodes/llm/Panel.tsx
import { Form, Input, InputNumber, Alert, Select, App, Collapse, Divider } from "antd";
import { useState, useEffect } from "react";
import { ModelSelector } from "@/components/workflow/ModelSelector";
import { VarReferencePicker } from "@/components/workflow/_base/variable/VarReferencePicker";
import { useDebouncedCallback } from "@/app/dashboard/workflow/_base/hooks/useDebouncedCallback";
import { skillsApi, type InstalledSkill } from "@/services/skills";
import { AdvancedOptions } from "@/components/workflow/_base/error/AdvancedOptions";
import type { PanelProps } from "../registry";
import type { ValueSelector } from "@/components/workflow/_base/variable/types";

export function LLMPanel({ node, nodes, edges, onChange }: PanelProps) {
  const { message } = App.useApp();
  const cfg = (node.config ?? {}) as Record<string, any>;
  const debouncedOnChange = useDebouncedCallback(
    (next: typeof node) => onChange(next),
    200
  );
  const update = (patch: Record<string, any>) =>
    debouncedOnChange({ ...node, config: { ...cfg, ...patch } });

  const [variablesText, setVariablesText] = useState<string>(() => {
    if (!cfg.variables) return "{}";
    try { return JSON.stringify(cfg.variables, null, 2); } catch { return "{}"; }
  });
  useEffect(() => {
    try { setVariablesText(JSON.stringify(cfg.variables ?? {}, null, 2)); } catch {}
  }, [node.id]);

  const [installedOptions, setInstalledOptions] = useState<
    { value: number; label: string; category: string }[]
  >([]);

  useEffect(() => {
    setInstalledOptions([]);
    let cancelled = false;
    (async () => {
      try {
        const res = await skillsApi.listInstalled(1, 50);
        if (cancelled) return;
        if (res.data.code === 200) {
          // PaginatedResponse: data is the array directly (no extra .data nesting)
          const list = Array.isArray(res.data.data) ? res.data.data : [];
          setInstalledOptions(
            list.map((s: InstalledSkill) => ({
              value: s.skill_id,
              label: s.name,
              category: s.category,
            }))
          );
        } else {
          message.error(res.data.message || "加载已装技能失败");
        }
      } catch {
        if (cancelled) return;
        message.error("加载已装技能失败");
      }
    })();
    return () => { cancelled = true; };
  }, [node.id]);

  const modelSelectorValue =
    cfg.model_config_id != null || cfg.model_name
      ? { model_config_id: cfg.model_config_id ?? null, model_name: cfg.model_name ?? "" }
      : undefined;

  const insertIntoPrompt = (selector: ValueSelector) => {
    const token = `{{#${selector.join(".")}#}}`;
    const current = cfg.prompt ?? "";
    update({ prompt: current ? `${current} ${token}` : token });
  };

  // Collapsible sections: basic / model / prompt / advanced
  const collapseItems = [
    {
      key: "basic",
      label: <span style={{ fontSize: 13, fontWeight: 500 }}>基本配置</span>,
      children: (
        <Form layout="vertical" size="small">
          <Form.Item label="节点名称" style={{ marginBottom: 8 }}>
            <Input
              value={cfg.title ?? ""}
              onChange={(e) => update({ title: e.target.value })}
              placeholder="给节点起个名字"
            />
          </Form.Item>
        </Form>
      ),
    },
    {
      key: "model",
      label: <span style={{ fontSize: 13, fontWeight: 500 }}>模型配置</span>,
      children: (
        <Form layout="vertical" size="small">
          <Form.Item label="模型" style={{ marginBottom: 8 }}>
            <ModelSelector
              value={modelSelectorValue}
              onChange={(v) => update({ model_config_id: v.model_config_id, model_name: v.model_name })}
            />
          </Form.Item>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <Form.Item label="Temperature" style={{ marginBottom: 0 }}>
              <InputNumber
                min={0} max={2} step={0.1}
                value={typeof cfg.temperature === "number" ? cfg.temperature : 0.7}
                onChange={(v) => update({ temperature: v ?? 0.7 })}
                style={{ width: "100%" }}
              />
            </Form.Item>
            <Form.Item label="Max Tokens" style={{ marginBottom: 0 }}>
              <InputNumber
                min={1} max={32768} step={1}
                value={cfg.max_tokens ?? undefined}
                placeholder="可选"
                onChange={(v) => update({ max_tokens: v ?? null })}
                style={{ width: "100%" }}
              />
            </Form.Item>
          </div>
        </Form>
      ),
    },
    {
      key: "prompt",
      label: <span style={{ fontSize: 13, fontWeight: 500 }}>Prompt</span>,
      children: (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <Alert
            type="info"
            showIcon
            message="使用 {{#node_id.var#}} 引用上游变量"
          />
          <Form.Item label="Prompt 模板" style={{ marginBottom: 6 }}>
            <Input.TextArea
              rows={4}
              value={cfg.prompt ?? ""}
              onChange={(e) => update({ prompt: e.target.value })}
              placeholder='例如: 请把 {{#input.user_query#}} 翻译成英文'
            />
          </Form.Item>
          <Form.Item label="插入变量" style={{ marginBottom: 6 }}>
            <VarReferencePicker
              nodeId={node.id}
              nodes={nodes}
              edges={edges}
              value={null}
              onChange={insertIntoPrompt}
              placeholder="选择变量插入到 Prompt 末尾"
            />
          </Form.Item>
          <Form.Item label="System Prompt (可选)" style={{ marginBottom: 6 }}>
            <Input.TextArea
              rows={2}
              value={cfg.system_prompt ?? ""}
              onChange={(e) => update({ system_prompt: e.target.value })}
              placeholder="可选的系统提示词"
            />
          </Form.Item>
          <Form.Item label="已安装技能 (可选)" style={{ marginBottom: 0 }}>
            <Select
              mode="multiple"
              allowClear
              virtual={false}
              placeholder="从已装技能中选择(最多5个)"
              value={cfg.skill_ids || []}
              onChange={(v) => update({ skill_ids: (v as number[]).slice(0, 5) })}
              options={installedOptions}
              optionFilterProp="label"
              maxTagCount={3}
              style={{ width: "100%" }}
            />
          </Form.Item>
        </div>
      ),
    },
    {
      key: "variables",
      label: <span style={{ fontSize: 13, fontWeight: 500 }}>静态变量</span>,
      children: (
        <Form.Item label="静态变量 (JSON)" style={{ marginBottom: 0 }}>
          <Input.TextArea
            rows={4}
            value={variablesText}
            onChange={(e) => {
              const text = e.target.value;
              setVariablesText(text);
              try {
                const parsed = JSON.parse(text || "{}");
                if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
                  update({ variables: parsed });
                }
              } catch {}
            }}
            placeholder='{"key": "value"}'
            style={{ fontFamily: "monospace", fontSize: 12 }}
          />
        </Form.Item>
      ),
    },
    {
      key: "advanced",
      label: <span style={{ fontSize: 13, fontWeight: 500 }}>高级选项</span>,
      children: (
        <AdvancedOptions
          config={{
            error_strategy: cfg.error_strategy ?? null,
            default_value: cfg.default_value ?? null,
            retry_config: cfg.retry_config ?? null,
            timeout: cfg.timeout ?? null,
          }}
          onChange={update}
        />
      ),
    },
  ];

  return (
    <div>
      {/* Node name — always visible at top for quick access */}
      <Form layout="vertical" size="small" style={{ marginBottom: 8 }}>
        <Form.Item label="节点名称" style={{ marginBottom: 0 }}>
          <Input
            value={cfg.title ?? ""}
            onChange={(e) => update({ title: e.target.value })}
            placeholder="给 LLM 节点起个名字"
          />
        </Form.Item>
      </Form>
      <Divider style={{ margin: "4px 0 8px" }} />
      <Collapse
        ghost
        defaultActiveKey={["model", "prompt"]}
        items={collapseItems}
      />
    </div>
  );
}
