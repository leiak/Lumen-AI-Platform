"use client";
import { Alert, Button, Form, Input, Space, Table } from "antd";
import { useState } from "react";
import { AdvancedOptions } from "../../_base/error/AdvancedOptions";
import { useAvailableVarList } from "../../_base/hooks/useAvailableVarList";
import { VarReferencePopup } from "../../_base/variable/VarReferencePopup";
import { ToolSelector } from "../../ToolSelector";
import type { PanelProps } from "../registry";
import { nodeData } from "../registry";
import type { ToolNodeConfig } from "./types";

export function ToolPanel({ node, nodes, edges, onChange }: PanelProps) {
  const cfg = nodeData(node) as ToolNodeConfig;
  const update = (patch: Partial<ToolNodeConfig>) =>
    onChange({ ...node, config: { ...cfg, ...patch } });

  const args = (cfg.arguments ?? {}) as Record<string, string>;
  const vars = useAvailableVarList(node.id, nodes, edges);
  const argRows = Object.entries(args).map(([k, v]) => ({ key: k, value: v }));
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [newKey, setNewKey] = useState("");
  // Per-row popover open state so multiple "插入" buttons can be clicked independently.
  const [pickerOpen, setPickerOpen] = useState<Record<string, boolean>>({});

  const handleArgChange = (key: string, value: string) => {
    update({ arguments: { ...args, [key]: value } });
  };
  const insertVar = (key: string, sel: string[]) => {
    const ref = `{{#${sel.join(".")}#}}`;
    handleArgChange(key, (args[key] ?? "") + ref);
  };
  const removeArg = (key: string) => {
    const next = { ...args };
    delete next[key];
    update({ arguments: next });
  };
  const addArg = () => {
    if (!newKey.trim()) return;
    update({ arguments: { ...args, [newKey]: "" } });
    setNewKey("");
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Alert
        type="info"
        showIcon
        message="工具节点引用平台已注册的 MCP 工具"
      />

      <Form.Item label="工具" style={{ marginBottom: 0 }}>
        <ToolSelector
          value={cfg.tool_id ?? null}
          toolNameCache={cfg.tool_name_cache ?? ""}
          onChange={(id, name) =>
            update({ tool_id: id ?? undefined, tool_name_cache: name })
          }
        />
      </Form.Item>

      {cfg.tool_id != null && cfg.tool_id !== 0 && (
        <Form.Item label="参数" style={{ marginBottom: 0 }}>
          <Space.Compact style={{ width: "100%", marginBottom: 8 }}>
            <Input
              placeholder="参数名 (key)"
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
              onPressEnter={addArg}
            />
            <Button type="primary" onClick={addArg}>
              添加
            </Button>
          </Space.Compact>
          <Table
            size="small"
            dataSource={argRows}
            rowKey="key"
            pagination={false}
            locale={{ emptyText: "暂无参数,可在上方添加" }}
            columns={[
              { title: "Key", dataIndex: "key", width: 120 },
              {
                title: "Value",
                dataIndex: "value",
                render: (_, r) =>
                  editingKey === r.key ? (
                    <Input
                      value={r.value}
                      onChange={(e) =>
                        handleArgChange(r.key, e.target.value)
                      }
                      onBlur={() => setEditingKey(null)}
                      onPressEnter={() => setEditingKey(null)}
                      autoFocus
                    />
                  ) : (
                    <div
                      onClick={() => setEditingKey(r.key)}
                      style={{
                        cursor: "pointer",
                        fontFamily: "monospace",
                        fontSize: 12,
                      }}
                    >
                      {r.value || (
                        <span style={{ color: "#bfbfbf" }}>(空)</span>
                      )}
                    </div>
                  ),
              },
              {
                title: "插入变量",
                width: 100,
                render: (_, r) => (
                  <VarReferencePopup
                    open={!!pickerOpen[r.key]}
                    onOpenChange={(b) =>
                      setPickerOpen((prev) => ({ ...prev, [r.key]: b }))
                    }
                    vars={vars}
                    onPick={(v) => {
                      insertVar(r.key, [v.nodeId, v.variable]);
                      setPickerOpen((prev) => ({
                        ...prev,
                        [r.key]: false,
                      }));
                    }}
                  >
                    <Button size="small">插入</Button>
                  </VarReferencePopup>
                ),
              },
              {
                title: "",
                width: 60,
                render: (_, r) => (
                  <Button
                    size="small"
                    danger
                    onClick={() => removeArg(r.key)}
                  >
                    删除
                  </Button>
                ),
              },
            ]}
          />
        </Form.Item>
      )}

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
