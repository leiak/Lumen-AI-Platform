"use client";
import { Alert, Form, Input } from "antd";
import { AdvancedOptions } from "../../_base/error/AdvancedOptions";
import { useDebouncedCallback } from "@/app/dashboard/workflow/_base/hooks/useDebouncedCallback";
import type { PanelProps } from "../registry";
import { nodeData } from "../registry";
import type { CodeNodeConfig } from "./types";

export function CodePanel({ node, onChange }: PanelProps) {
  const cfg = nodeData(node) as CodeNodeConfig;

  // M30 收口-A: debounce the canvas commit so a burst of keystrokes
  // (the code editor is a common offender) collapses to one
  // setNodes + canvas re-render. 200ms feels instant for typing.
  const debouncedOnChange = useDebouncedCallback(
    (next: typeof node) => onChange(next),
    200
  );
  const update = (patch: Partial<CodeNodeConfig>) =>
    debouncedOnChange({ ...node, config: { ...cfg, ...patch } });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Alert
        type="warning"
        showIcon
        message="RestrictedPython 沙箱:禁止 import / file I/O / network"
      />

      <Form.Item label="Python 源码" style={{ marginBottom: 0 }}>
        <Input.TextArea
          rows={10}
          value={cfg.code ?? ""}
          onChange={(e) => update({ code: e.target.value })}
          placeholder="RESULT = 1 + 1"
          style={{ fontFamily: "monospace" }}
        />
      </Form.Item>

      <Form.Item label="输出变量名(代码里要设置的变量)" style={{ marginBottom: 0 }}>
        <Input
          value={cfg.output_var ?? "RESULT"}
          onChange={(e) => update({ output_var: e.target.value })}
          placeholder="RESULT"
        />
      </Form.Item>

      <Form.Item
        label="inputs_mapping(P2 简化:UI 仅做提示,后端解析 dot-path)"
        style={{ marginBottom: 0 }}
      >
        <Input.TextArea
          rows={3}
          value={JSON.stringify(cfg.inputs_mapping ?? {}, null, 2)}
          onChange={(e) => {
            try {
              update({ inputs_mapping: JSON.parse(e.target.value) });
            } catch {
              /* ignore parse */
            }
          }}
          placeholder='{"x": "input.user_query"}'
        />
      </Form.Item>

      <AdvancedOptions
        config={{
          error_strategy: cfg.error_strategy ?? null,
          default_value: cfg.default_value ?? null,
          retry_config: cfg.retry_config ?? null,
          timeout: cfg.timeout ?? null,
        }}
        onChange={(patch) => update(patch)}
      />
    </div>
  );
}
