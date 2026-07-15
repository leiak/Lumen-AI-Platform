"use client";

import { useEffect } from "react";
import Link from "next/link";
import { Alert, Select, Tag } from "antd";
import { useQuery } from "@tanstack/react-query";
import { modelsApi, ModelConfig } from "@/services/models";

interface Props {
  value?: number;
  onChange?: (val: number) => void;
  disabled?: boolean;
  /**
   * Fired with the freshly-loaded list of active embedding models.
   * The parent uses this to auto-pick a default for the create-KB
   * form once data is in hand (no flash, no manual click).
   */
  onLoaded?: (models: ModelConfig[]) => void;
}

// Map model_type → AntD tag color so the dropdown is scannable at a
// glance. Stays a small const rather than theme tokens to keep the
// component standalone (no app-level theme coupling).
const PROVIDER_COLOR: Record<string, string> = {
  ollama: "blue",
  openai: "green",
  deepseek: "purple",
  anthropic: "volcano",
  cohere: "magenta",
  huggingface: "orange",
};

export default function EmbeddingModelSelect({
  value,
  onChange,
  disabled,
  onLoaded,
}: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["embedding-models"],
    queryFn: async () => {
      const res = await modelsApi.list(1, 100, { is_embedding: true, is_active: true });
      if (res.data?.code === 200) {
        return res.data.data as ModelConfig[];
      }
      return [];
    },
    staleTime: 30_000,
  });

  // Surface the loaded list to the parent. Done in an effect (not
  // during render) so the parent's setState never fires mid-render
  // and a re-render with the same array doesn't re-invoke the
  // callback unnecessarily.
  useEffect(() => {
    if (onLoaded && data) {
      onLoaded(data);
    }
    // We intentionally depend only on the data identity; the parent
    // callback may be re-created each render and we don't want to
    // refire on every parent re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const list = data || [];
  const hasNoModels = !isLoading && list.length === 0;

  const options = list.map((m) => {
    // `label` doubles as the filterable text (optionFilterProp="label"
    // is the default). Include model_type so typing "ollama" matches
    // Ollama models.
    const label = `${m.name} (${m.model_name}) · ${m.model_type}`;
    return {
      value: m.id,
      label,
      // Pass raw fields through so `optionRender` can compose JSX
      // (Tag) without re-parsing the label string.
      name: m.name,
      model_name: m.model_name,
      model_type: m.model_type,
      is_default: m.is_default,
    };
  });

  return (
    <div>
      <Select
        value={value}
        onChange={onChange}
        disabled={disabled || isLoading}
        loading={isLoading}
        placeholder={hasNoModels ? "暂无可用 Embedding 模型" : "选择 embedding 模型"}
        showSearch
        optionFilterProp="label"
        options={options}
        // Disable AntD 5's default `rc-virtual-list` virtualization.
        // This dropdown holds at most a handful of embedding models per
        // tenant; virtual scrolling only hurts here by mis-measuring
        // custom optionRender heights and dropping non-active options
        // from the rendered DOM (jsdom test breakage + no real perf
        // win for <=10 rows). The always-render cost is negligible.
        virtual={false}
        style={{ width: "100%" }}
        optionRender={(option) => {
          // `option.data` is the original object we put into `options`.
          const o = option.data as {
            name: string;
            model_name: string;
            model_type: string;
            is_default: boolean;
          };
          return (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 8,
              }}
            >
              <span
                style={{
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {o.name} <span style={{ color: "#999" }}>({o.model_name})</span>
              </span>
              <span style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                {o.is_default && (
                  <Tag color="gold" style={{ marginRight: 0 }}>
                    默认
                  </Tag>
                )}
                <Tag
                  color={PROVIDER_COLOR[o.model_type] || "default"}
                  style={{ marginRight: 0 }}
                >
                  {o.model_type}
                </Tag>
              </span>
            </div>
          );
        }}
      />
      {disabled && (
        <div style={{ fontSize: 12, color: "#999", marginTop: 4 }}>
          创建后不可更改
        </div>
      )}
      {/* Empty state — when no active embedding model exists the
          Select itself is just an empty box. Surface a clear CTA so
          the user knows where to go. The Alert is component-local so
          every call site (create / edit / future flows) gets it for
          free. */}
      {hasNoModels && (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 8 }}
          message="暂无可用 Embedding 模型"
          description={
            <>
              请先前往{" "}
              <Link href="/dashboard/system/models">系统模型管理</Link>{" "}
              添加一个 <code>is_embedding=true</code> 且 <code>is_active=true</code>{" "}
              的模型,然后刷新本页面。
            </>
          }
        />
      )}
    </div>
  );
}
