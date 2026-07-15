"use client";

import { useEffect, useMemo, useState } from "react";
import { Select, Alert, Space } from "antd";
import { mcpApi, type MCPTool } from "@/services/mcp";

const MISSING_VALUE = "__missing__";

export interface ToolSelectorProps {
  value: number | null;
  toolNameCache: string;
  onChange: (toolId: number | null, toolName: string) => void;
}

export function ToolSelector({ value, toolNameCache, onChange }: ToolSelectorProps) {
  const [tools, setTools] = useState<MCPTool[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refetch = async () => {
    try {
      const res = await mcpApi.listTools(1, 100);
      if (res.data.code === 200) {
        setTools(res.data.data);
        setLoadError(null);
      } else {
        setLoadError(res.data.message ?? "加载失败");
      }
    } catch (err: any) {
      setLoadError(err?.message ?? "网络错误");
    }
  };

  useEffect(() => {
    refetch();
  }, []);

  // Backend already filters is_enabled == 1 at the SQL level, but apply a
  // defensive client-side filter so the selector stays consistent if a tool
  // is disabled via the MCP management page while the user is editing.
  const enabledTools = useMemo(
    () => (tools ?? []).filter((t) => (t.is_enabled ?? 1) !== 0),
    [tools]
  );

  const isMissing =
    value != null && !enabledTools.some((t) => t.id === value);

  const selectedValue: string | undefined = useMemo(() => {
    if (value == null) return undefined;
    const hit = enabledTools.find((t) => t.id === value);
    return hit ? String(hit.id) : MISSING_VALUE;
  }, [value, enabledTools]);

  const options = useMemo(() => {
    const opts = enabledTools.map((t) => ({
      label: t.name,
      value: String(t.id),
    }));
    if (isMissing) {
      const label = toolNameCache
        ? `⚠️ (已删除) ${toolNameCache}`
        : "⚠️ (已删除)";
      opts.push({ label, value: MISSING_VALUE });
    }
    return opts;
  }, [enabledTools, isMissing, toolNameCache]);

  const handleChange = (v: string) => {
    if (v === MISSING_VALUE) {
      // Re-clicking the missing sentinel: keep the cached value so the user
      // can re-pick or rebuild it from the dropdown.
      onChange(value, toolNameCache);
      return;
    }
    const t = enabledTools.find((x) => x.id === Number(v));
    if (!t) return;
    onChange(t.id, t.name);
  };

  if (loadError) {
    return (
      <Space direction="vertical" style={{ width: "100%" }}>
        <Alert
          type="error"
          showIcon
          message="MCP 工具数据加载失败,请刷新重试"
          description={loadError}
        />
      </Space>
    );
  }

  return (
    <>
      <Select
        showSearch
        allowClear
        placeholder="选择 MCP 工具"
        value={selectedValue}
        options={options}
        onChange={handleChange}
        onClear={() => onChange(null, "")}
        style={{ width: "100%" }}
        optionLabelProp="label"
        filterOption={(input, option) =>
          (option?.label ?? "")
            .toString()
            .toLowerCase()
            .includes(input.toLowerCase())
        }
      />
      {isMissing && (
        <div
          style={{
            marginTop: 6,
            padding: "4px 8px",
            background: "#fffbe6",
            border: "1px solid #ffe58f",
            borderRadius: 4,
            color: "#ad6800",
            fontSize: 12,
          }}
        >
          原工具已失效 ({toolNameCache || "未知"})。请重新选择或在 MCP 工具管理中重建。
        </div>
      )}
    </>
  );
}

export default ToolSelector;
