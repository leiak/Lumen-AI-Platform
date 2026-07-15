"use client";

import Link from "next/link";
import { Alert, Select, Tag } from "antd";
import { useQuery } from "@tanstack/react-query";
import { modelsApi, ModelConfig } from "@/services/models";

interface Props {
  value?: number | null;
  onChange?: (val: number) => void;
  disabled?: boolean;
}

// Map model_type → AntD tag color so the dropdown is scannable at a
// glance. Mirrors `EmbeddingModelSelect`'s PROVIDER_COLOR so chat and
// embedding dropdowns look consistent on the settings page.
const PROVIDER_COLOR: Record<string, string> = {
  ollama: "blue",
  openai: "green",
  deepseek: "purple",
  anthropic: "volcano",
  cohere: "magenta",
  huggingface: "orange",
  minimax: "geekblue",
};

export default function ChatModelSelect({ value, onChange, disabled }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["chat-models"],
    queryFn: async () => {
      const res = await modelsApi.list(1, 100, { is_chat: true, is_active: true });
      if (res.data?.code === 200) {
        return res.data.data as ModelConfig[];
      }
      return [];
    },
    staleTime: 30_000,
  });

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
        placeholder={hasNoModels ? "暂无可用 Chat 模型" : "选择聊天模型"}
        showSearch
        optionFilterProp="label"
        options={options}
        // Disable AntD 5's default `rc-virtual-list` virtualization.
        // This dropdown holds at most a handful of chat models per
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
      {/* Empty state — when no active chat model exists the Select
          itself is just an empty box. Surface a clear CTA so the user
          knows where to go. The Alert is component-local so every
          call site (settings, future flows) gets it for free. */}
      {hasNoModels && (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 8 }}
          message="暂无可用 Chat 模型"
          description={
            <>
              请先前往{" "}
              <Link href="/dashboard/system/models">系统模型管理</Link>{" "}
              添加一个 <code>is_chat=true</code> 且 <code>is_active=true</code>{" "}
              的模型,然后刷新本页面。
            </>
          }
        />
      )}
    </div>
  );
}
