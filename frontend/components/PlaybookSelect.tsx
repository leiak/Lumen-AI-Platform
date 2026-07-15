"use client";

// M35: PlaybookSelect — 选 playbook 的通用组件
// 用于 image-generation / TTS 等多模态创作入口。
// virtual={false} 兜底小列表(MEMORY 2026-06-08:antd v5 Select +
// virtual=true + 自定义 optionRender 容易吞掉小列表 option)。

import { useEffect, useState } from "react";
import { Select, App } from "antd";
import { listPlaybooks } from "@/services/playbook";
import type { PlaybookListItem } from "@/types/playbook";

export interface PlaybookSelectProps {
  scope?: "image" | "tts" | "video";
  value?: number | null;
  onChange?: (value: number | null) => void;
  allowClear?: boolean;
  placeholder?: string;
  disabled?: boolean;
  style?: React.CSSProperties;
}

export default function PlaybookSelect({
  scope,
  value,
  onChange,
  allowClear = true,
  placeholder = "选择 Playbook (可选)",
  disabled,
  style,
}: PlaybookSelectProps) {
  const { message } = App.useApp();
  const [items, setItems] = useState<PlaybookListItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const res = await listPlaybooks({
          scope: scope || undefined,
          page: 1,
          page_size: 100,
        });
        setItems(res.items);
      } catch (e) {
        message.error(`加载 Playbook 失败: ${(e as Error).message}`);
      } finally {
        setLoading(false);
      }
    })();
  }, [scope, message]);

  return (
    <Select
      value={value ?? undefined}
      onChange={(v) => onChange?.(v ?? null)}
      allowClear={allowClear}
      placeholder={placeholder}
      loading={loading}
      disabled={disabled}
      style={style}
      virtual={false}  // M35 fix: small list + custom render → disable virtual
      options={items.map((p) => ({
        label: `${p.name}${p.is_builtin ? " (内置)" : ""}`,
        value: p.id,
      }))}
    />
  );
}
