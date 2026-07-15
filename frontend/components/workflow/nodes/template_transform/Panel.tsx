"use client";
import { Form, Input, Alert, Button } from "antd";
import { useState } from "react";
import { AdvancedOptions } from "../../_base/error/AdvancedOptions";
import { useAvailableVarList } from "../../_base/hooks/useAvailableVarList";
import { useDebouncedCallback } from "@/app/dashboard/workflow/_base/hooks/useDebouncedCallback";
import { nodesApi } from "@/services/nodes";
import type { PanelProps } from "../registry";
import { nodeData } from "../registry";

export function TemplateTransformPanel({ node, nodes, edges, onChange }: PanelProps) {
  const cfg = nodeData(node) as any;
  // M30 收口-A: debounce commit to canvas.
  const debouncedOnChange = useDebouncedCallback(
    (next: typeof node) => onChange(next),
    200
  );
  const update = (patch: Record<string, unknown>) =>
    debouncedOnChange({ ...node, config: { ...cfg, ...patch } });
  const vars = useAvailableVarList(node.id ?? "", nodes, edges);
  const [preview, setPreview] = useState<any>(null);

  const onTest = async () => {
    const res = await nodesApi.previewTemplate({
      template: cfg.template ?? "",
      sample_context: {},
    });
    setPreview(res.data);
  };

  const insertVar = (sel: string[]) =>
    update({ template: (cfg.template ?? "") + `{{ ${sel.join(".")} }}` });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Alert
        type="info"
        showIcon
        message="Jinja2 语法:支持 if / for / filter,{{ node_id.var }} 引用"
      />
      <Form.Item label="模板">
        <Input.TextArea
          rows={12}
          value={cfg.template ?? ""}
          onChange={(e) => update({ template: e.target.value })}
          style={{ fontFamily: "monospace" }}
        />
      </Form.Item>
      <div style={{ fontSize: 12, color: "#8c8c8c" }}>
        可用变量(点击插入到末尾):
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {vars.map((v: any) => (
          <Button
            size="small"
            key={`${v.nodeId}.${v.variable}`}
            onClick={() => insertVar([v.nodeId, v.variable])}
          >
            {v.nodeId}.{v.variable}
          </Button>
        ))}
      </div>
      <div>
        <Button onClick={onTest}>实时预览</Button>
        {preview && (
          <Alert
            style={{ marginTop: 8 }}
            type="info"
            message={
              <pre style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>
                {JSON.stringify(preview, null, 2)}
              </pre>
            }
          />
        )}
      </div>
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
