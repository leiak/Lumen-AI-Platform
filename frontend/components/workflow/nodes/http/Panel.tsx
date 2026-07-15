"use client";
import {
  Alert,
  App,
  Button,
  Collapse,
  Form,
  Input,
  Radio,
  Select,
  Space,
  Switch,
} from "antd";
import { useState } from "react";
import { AdvancedOptions } from "../../_base/error/AdvancedOptions";
import { useAvailableVarList } from "../../_base/hooks/useAvailableVarList";
import { VarReferencePopup } from "../../_base/variable/VarReferencePopup";
import { nodesApi } from "@/services/nodes";
import type { PanelProps } from "../registry";
import { nodeData } from "../registry";
import type { HTTPNodeConfig } from "./types";
import { EditableKeyValueTable } from "./EditableKeyValueTable";
import { useDebouncedCallback } from "@/app/dashboard/workflow/_base/hooks/useDebouncedCallback";

type PreviewState =
  | { code: number; data?: { status_code?: number; [k: string]: unknown } | null; error?: string }
  | null;

export function HTTPPanel({ node, nodes, edges, onChange }: PanelProps) {
  // M30c: App.useApp() so the JSON.parse error toast actually
  // appears (the static import was unreliable in Next.js strict mode).
  const { message } = App.useApp();
  const cfg = nodeData(node) as HTTPNodeConfig;
  // M30 收口-A: debounce the canvas commit so a burst of
  // keystrokes in the body TextArea / auth inputs collapses to
  // one setNodes + canvas re-render.
  const debouncedOnChange = useDebouncedCallback(
    (next: typeof node) => onChange(next),
    200
  );
  const update = (patch: Partial<HTTPNodeConfig>) =>
    debouncedOnChange({ ...node, config: { ...cfg, ...patch } });

  const [preview, setPreview] = useState<PreviewState>(null);
  const [testing, setTesting] = useState(false);
  const [urlPickerOpen, setUrlPickerOpen] = useState(false);
  const [jsonError, setJsonError] = useState<string | null>(null);
  const availableVars = useAvailableVarList(node.id, nodes, edges);

  const onTest = async () => {
    setTesting(true);
    try {
      const res = await nodesApi.previewHTTP({
        method: cfg.method ?? "GET",
        url: cfg.url ?? "",
        headers: cfg.headers ?? {},
        query_params: cfg.query_params ?? {},
        body_type: cfg.body_type ?? "none",
        body: cfg.body ?? "",
        auth_type: cfg.auth_type ?? "none",
        auth_config: cfg.auth_config ?? {},
        verify_ssl: cfg.verify_ssl ?? true,
        follow_redirects: cfg.follow_redirects ?? true,
      });
      setPreview((res as { data: PreviewState }).data);
    } catch (e) {
      setPreview({ code: 500, data: null, error: String(e) });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Form.Item label="Method" style={{ marginBottom: 0 }}>
        <Select
          value={cfg.method ?? "GET"}
          onChange={(v) => update({ method: v })}
          options={["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => ({
            value: m,
            label: m,
          }))}
        />
      </Form.Item>

      <Form.Item label="URL" style={{ marginBottom: 0 }}>
        <Space.Compact style={{ width: "100%" }}>
          <Input
            value={cfg.url ?? ""}
            onChange={(e) => update({ url: e.target.value })}
            placeholder="https://api.example.com/v1/resource"
          />
          <VarReferencePopup
            open={urlPickerOpen}
            onOpenChange={setUrlPickerOpen}
            vars={availableVars}
            onPick={(v) => {
              update({
                url:
                  (cfg.url ?? "") +
                  `{{#${[v.nodeId, v.variable].join(".")}#}}`,
              });
              setUrlPickerOpen(false);
            }}
          >
            <Button onClick={() => setUrlPickerOpen(true)}>变量</Button>
          </VarReferencePopup>
        </Space.Compact>
      </Form.Item>

      <Collapse
        ghost
        items={[
          {
            key: "headers",
            label: "Headers",
            children: (
              <EditableKeyValueTable
                value={cfg.headers ?? {}}
                onChange={(next) => update({ headers: next })}
                keyPlaceholder="Header-Name"
                valuePlaceholder="Header-Value"
              />
            ),
          },
          {
            key: "query",
            label: "Query Params",
            children: (
              <EditableKeyValueTable
                value={cfg.query_params ?? {}}
                onChange={(next) => update({ query_params: next })}
                keyPlaceholder="param_name"
                valuePlaceholder="param_value"
              />
            ),
          },
          {
            key: "body",
            label: "Body",
            children: (
              <div
                style={{ display: "flex", flexDirection: "column", gap: 8 }}
              >
                <Radio.Group
                  value={cfg.body_type ?? "none"}
                  onChange={(e) => update({ body_type: e.target.value })}
                >
                  <Radio.Button value="none">none</Radio.Button>
                  <Radio.Button value="json">json</Radio.Button>
                  <Radio.Button value="form">form-urlencoded</Radio.Button>
                  <Radio.Button value="raw">raw</Radio.Button>
                </Radio.Group>
                {cfg.body_type && cfg.body_type !== "none" && (
                  <Input.TextArea
                    rows={5}
                    value={
                      typeof cfg.body === "string"
                        ? cfg.body
                        : JSON.stringify(cfg.body ?? {}, null, 2)
                    }
                    onChange={(e) => update({ body: e.target.value })}
                    style={{ fontFamily: "monospace" }}
                  />
                )}
              </div>
            ),
          },
          {
            key: "auth",
            label: "鉴权",
            children: (
              <div
                style={{ display: "flex", flexDirection: "column", gap: 8 }}
              >
                <Radio.Group
                  value={cfg.auth_type ?? "none"}
                  onChange={(e) =>
                    update({ auth_type: e.target.value, auth_config: {} })
                  }
                >
                  <Radio.Button value="none">none</Radio.Button>
                  <Radio.Button value="bearer">Bearer</Radio.Button>
                  <Radio.Button value="basic">Basic</Radio.Button>
                  <Radio.Button value="api_key">API Key</Radio.Button>
                  <Radio.Button value="custom_header">Custom Header</Radio.Button>
                </Radio.Group>
                {cfg.auth_type === "bearer" && (
                  <Input.Password
                    placeholder="token"
                    value={cfg.auth_config?.token ?? ""}
                    onChange={(e) =>
                      update({ auth_config: { token: e.target.value } })
                    }
                  />
                )}
                {cfg.auth_type === "basic" && (
                  <Space>
                    <Input
                      placeholder="username"
                      value={cfg.auth_config?.username ?? ""}
                      onChange={(e) =>
                        update({
                          auth_config: {
                            ...cfg.auth_config,
                            username: e.target.value,
                          },
                        })
                      }
                    />
                    <Input.Password
                      placeholder="password"
                      value={cfg.auth_config?.password ?? ""}
                      onChange={(e) =>
                        update({
                          auth_config: {
                            ...cfg.auth_config,
                            password: e.target.value,
                          },
                        })
                      }
                    />
                  </Space>
                )}
                {cfg.auth_type === "api_key" && (
                  <Space>
                    <Input
                      placeholder="header_name"
                      value={cfg.auth_config?.header_name ?? ""}
                      onChange={(e) =>
                        update({
                          auth_config: {
                            ...cfg.auth_config,
                            header_name: e.target.value,
                          },
                        })
                      }
                    />
                    <Input.Password
                      placeholder="api_key"
                      value={cfg.auth_config?.api_key ?? ""}
                      onChange={(e) =>
                        update({
                          auth_config: {
                            ...cfg.auth_config,
                            api_key: e.target.value,
                          },
                        })
                      }
                    />
                  </Space>
                )}
                {cfg.auth_type === "custom_header" && (
                  <div>
                    <Input.TextArea
                      rows={3}
                      placeholder='{"X-Foo": "bar"}'
                      value={JSON.stringify(cfg.auth_config ?? {}, null, 2)}
                      onChange={(e) => {
                        try {
                          const parsed = JSON.parse(e.target.value);
                          setJsonError(null);
                          update({ auth_config: parsed });
                        } catch (err: any) {
                          // M30c: surface the JSON parse error to the
                          // user via message.error + inline Alert. The
                          // pre-M30c code silently swallowed it,
                          // leaving the user confused about why the
                          // auth config wasn't applying.
                          setJsonError(err?.message || "JSON 解析失败");
                          message.error(`JSON 解析失败: ${err?.message || ""}`);
                        }
                      }}
                    />
                    {jsonError && (
                      <Alert
                        type="error"
                        showIcon
                        style={{ marginTop: 4 }}
                        message="JSON 格式错误"
                        description={jsonError}
                      />
                    )}
                  </div>
                )}
              </div>
            ),
          },
          {
            key: "transport",
            label: "传输选项",
            children: (
              <Space direction="vertical">
                <Form.Item label="verify_ssl" style={{ marginBottom: 0 }}>
                  <Switch
                    checked={cfg.verify_ssl ?? true}
                    onChange={(v) => update({ verify_ssl: v })}
                  />
                </Form.Item>
                <Form.Item label="follow_redirects" style={{ marginBottom: 0 }}>
                  <Switch
                    checked={cfg.follow_redirects ?? true}
                    onChange={(v) => update({ follow_redirects: v })}
                  />
                </Form.Item>
              </Space>
            ),
          },
        ]}
      />

      <div>
        <Button type="primary" onClick={onTest} loading={testing}>
          测试请求
        </Button>
        {preview && (
          <Alert
            style={{ marginTop: 8 }}
            type={preview.code === 200 ? "success" : "error"}
            message={`Status: ${preview.data?.status_code ?? "?"}`}
            description={
              <pre style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>
                {JSON.stringify(preview.data ?? preview.error, null, 2)}
              </pre>
            }
          />
        )}
      </div>

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
