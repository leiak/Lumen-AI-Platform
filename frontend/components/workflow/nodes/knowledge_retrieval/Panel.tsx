"use client";
import { Alert, Button, Form, Input, InputNumber, Space, Switch } from "antd";
import { useState } from "react";
import { AdvancedOptions } from "../../_base/error/AdvancedOptions";
import { useAvailableVarList } from "../../_base/hooks/useAvailableVarList";
import { VarReferencePopup } from "../../_base/variable/VarReferencePopup";
import { KBSelector } from "../../KBSelector";
import { nodesApi } from "@/services/nodes";
import type { PanelProps } from "../registry";
import { nodeData } from "../registry";
import type { KBRetrievalConfig } from "./types";

type PreviewState =
  | {
      code: number;
      data?: { count?: number; [k: string]: unknown } | null;
      error?: string;
    }
  | null;

export function KBRetrievalPanel({ node, nodes, edges, onChange }: PanelProps) {
  const cfg = nodeData(node) as KBRetrievalConfig;
  const update = (patch: Partial<KBRetrievalConfig>) =>
    onChange({ ...node, config: { ...cfg, ...patch } });

  const vars = useAvailableVarList(node.id, nodes, edges);
  const [pickerOpen, setPickerOpen] = useState(false);

  const insertQueryVar = (v: { nodeId: string; variable: string }) => {
    const ref = `{{#${[v.nodeId, v.variable].join(".")}#}}`;
    update({ query: (cfg.query ?? "") + ref });
    setPickerOpen(false);
  };

  const [preview, setPreview] = useState<PreviewState>(null);
  const [testing, setTesting] = useState(false);
  const onTest = async () => {
    setTesting(true);
    try {
      const res = await nodesApi.previewKB({
        kb_id: cfg.kb_id ?? 0,
        query: cfg.query ?? "",
        top_k: cfg.top_k ?? 5,
        score_threshold: cfg.score_threshold ?? 0.0,
      });
      setPreview(
        (res as { data: PreviewState }).data ?? { code: 500, data: null }
      );
    } catch (e) {
      setPreview({ code: 500, data: null, error: String(e) });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Alert
        type="info"
        showIcon
        message="从已注册的知识库中检索与 query 相关的文档片段"
      />

      <Form.Item label="知识库" style={{ marginBottom: 0 }}>
        <KBSelector
          value={cfg.kb_id ? cfg.kb_id : null}
          kbNameCache={cfg.kb_name_cache ?? ""}
          onChange={(id, name) =>
            update({ kb_id: id ?? undefined, kb_name_cache: name })
          }
        />
      </Form.Item>

      <Form.Item label="Query" style={{ marginBottom: 0 }}>
        <Input.TextArea
          rows={3}
          value={cfg.query ?? ""}
          onChange={(e) => update({ query: e.target.value })}
          placeholder="支持 {{#node_id.var#}} 模板"
        />
        <div style={{ marginTop: 4 }}>
          <VarReferencePopup
            open={pickerOpen}
            onOpenChange={setPickerOpen}
            vars={vars}
            onPick={insertQueryVar}
          >
            <Button size="small">插入变量</Button>
          </VarReferencePopup>
        </div>
      </Form.Item>

      <Form.Item label="Top K" style={{ marginBottom: 0 }}>
        <InputNumber
          min={1}
          max={50}
          value={cfg.top_k ?? 5}
          onChange={(v) => update({ top_k: v ?? 5 })}
          style={{ width: "100%" }}
        />
      </Form.Item>

      <Form.Item label="Score Threshold" style={{ marginBottom: 0 }}>
        <InputNumber
          min={0}
          max={1}
          step={0.05}
          value={cfg.score_threshold ?? 0.0}
          onChange={(v) => update({ score_threshold: v ?? 0.0 })}
          style={{ width: "100%" }}
        />
      </Form.Item>

      <Form.Item label="重排序 (Rerank)" style={{ marginBottom: 0 }}>
        <Switch
          checked={cfg.rerank_enabled ?? true}
          onChange={(v) => update({ rerank_enabled: v })}
        />
      </Form.Item>

      <Form.Item label="混合检索 (Hybrid)" style={{ marginBottom: 0 }}>
        <Switch
          checked={cfg.hybrid_search ?? true}
          onChange={(v) => update({ hybrid_search: v })}
        />
      </Form.Item>

      <Space direction="vertical" style={{ width: "100%" }}>
        <Button type="primary" onClick={onTest} loading={testing}>
          测试检索
        </Button>
        {preview && (
          <Alert
            type={preview.code === 200 ? "success" : "error"}
            showIcon
            message={
              preview.code === 200
                ? `命中 ${preview.data?.count ?? 0} 个片段`
                : "检索失败"
            }
            description={
              <pre style={{ fontSize: 12, whiteSpace: "pre-wrap", margin: 0 }}>
                {preview.code === 200
                  ? JSON.stringify(preview.data ?? {}, null, 2)
                  : String(preview.error ?? "未知错误")}
              </pre>
            }
            style={{ marginTop: 8 }}
          />
        )}
      </Space>

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
