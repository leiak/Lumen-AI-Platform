"use client";
import { Form, Input, InputNumber, Select } from "antd";
import { useEffect, useState } from "react";

export function PromptFields() {
  return (
    <>
      <Form.Item name="content" label="Prompt 内容" rules={[{ required: true }]}>
        <Input.TextArea rows={6} placeholder="You are a helpful 助手..." />
      </Form.Item>
      <Form.Item name="provider" label="提供方">
        <Input placeholder="如 Lumen AI Platform" />
      </Form.Item>
    </>
  );
}

export function ScriptFields() {
  return (
    <>
      <Form.Item name={["type_config", "code"]} label="Python 代码" rules={[{ required: true }]}>
        <Input.TextArea
          rows={10}
          placeholder="def main(x): return x * 2"
          style={{ fontFamily: "Menlo, Consolas, monospace" }}
        />
      </Form.Item>
      <Form.Item name={["type_config", "runtime"]} label="运行时" initialValue="python-3.11">
        <Input />
      </Form.Item>
      <Form.Item name={["type_config", "timeout"]} label="超时 (秒)" initialValue={30}>
        <InputNumber min={1} max={120} />
      </Form.Item>
    </>
  );
}

export function HttpFields() {
  return (
    <>
      <Form.Item name={["type_config", "url"]} label="URL" rules={[{ required: true }]}>
        <Input placeholder="https://api.example.com/v1/..." />
      </Form.Item>
      <Form.Item name={["type_config", "method"]} label="方法" initialValue="GET">
        <Select
          options={[
            { value: "GET", label: "GET" },
            { value: "POST", label: "POST" },
            { value: "PUT", label: "PUT" },
            { value: "PATCH", label: "PATCH" },
            { value: "DELETE", label: "DELETE" },
          ]}
        />
      </Form.Item>
      <Form.Item name={["type_config", "timeout"]} label="超时 (秒)" initialValue={30}>
        <InputNumber min={1} max={120} />
      </Form.Item>
      <Form.Item
        name={["type_config", "auth", "type"]}
        label="认证类型"
        initialValue="bearer"
      >
        <Select
          options={[
            { value: "bearer", label: "Bearer Token" },
            { value: "api_key", label: "API Key (header)" },
            { value: "basic", label: "Basic Auth" },
          ]}
        />
      </Form.Item>
      <Form.Item
        name={["type_config", "auth", "credential_ref"]}
        label="凭证引用"
        extra="格式: ${ENV_VAR_NAME} — 实际值从 .env 读取"
        rules={[{ required: true, pattern: /^\$\{[A-Z_][A-Z0-9_]*\}$/ }]}
      >
        <Input placeholder="${OPENWEATHER_API_KEY}" />
      </Form.Item>
    </>
  );
}

interface KB { id: number; name: string }

export function KBFields() {
  const [kbs, setKbs] = useState<KB[]>([]);
  useEffect(() => {
    fetch("/api/v1/knowledge/")
      .then((r) => r.json())
      .then((j) => setKbs(j.data || []))
      .catch(() => setKbs([]));
  }, []);

  return (
    <>
      <Form.Item name={["type_config", "kb_id"]} label="知识库" rules={[{ required: true }]}>
        <Select
          options={kbs.map((k) => ({ value: k.id, label: k.name }))}
          placeholder="选择知识库"
        />
      </Form.Item>
      <Form.Item name={["type_config", "top_k"]} label="Top K" initialValue={5}>
        <InputNumber min={1} max={20} />
      </Form.Item>
      <Form.Item name={["type_config", "score_threshold"]} label="相似度阈值" initialValue={0.7}>
        <InputNumber min={0} max={1} step={0.05} />
      </Form.Item>
      <Form.Item
        name={["type_config", "query_template"]}
        label="查询模板"
        initialValue="{{user_query}}"
        extra="支持 {{arg_name}} 占位符"
      >
        <Input placeholder="{{user_query}}" />
      </Form.Item>
    </>
  );
}

interface Server { name: string; tools: string[] }

export function MCPFields() {
  const [servers, setServers] = useState<Server[]>([]);
  useEffect(() => {
    fetch("/api/v1/mcp/servers")
      .then((r) => r.json())
      .then((j) => setServers(j.data || []))
      .catch(() => setServers([]));
  }, []);

  return (
    <>
      <Form.Item name={["type_config", "mcp_server"]} label="MCP Server" rules={[{ required: true }]}>
        <Select
          options={servers.map((s) => ({ value: s.name, label: s.name }))}
          placeholder="选择 MCP server"
        />
      </Form.Item>
      <Form.Item name={["type_config", "tool_name"]} label="Tool" rules={[{ required: true }]}>
        <Input placeholder="list_workflows" />
      </Form.Item>
      <Form.Item name={["type_config", "param_schema"]} label="参数 Schema (JSON,可选)">
        <Input.TextArea
          rows={4}
          placeholder='{"type": "object", "properties": {...}}'
          style={{ fontFamily: "Menlo, Consolas, monospace" }}
        />
      </Form.Item>
    </>
  );
}
