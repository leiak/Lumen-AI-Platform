"use client";
import { useEffect, useState } from "react";
import { Select, Spin } from "antd";
import { fetchAllKBOptions, renderKBOption, type KBOption } from "@/components/workflow/kb-list";

export type MultiKBSelectorProps = {
  value?: number[];
  onChange?: (value: number[]) => void;
};

export function MultiKBSelector({ value, onChange }: MultiKBSelectorProps) {
  const [options, setOptions] = useState<KBOption[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const opts = await fetchAllKBOptions();
        if (!cancelled) setOptions(opts);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (loading) return <Spin size="small" />;

  return (
    <Select
      mode="multiple"
      value={value ?? []}
      onChange={onChange}
      placeholder="选择知识库(可多选)"
      optionFilterProp="children"
      virtual={false}  // M13 EmbeddingModelSelect fix:小列表不用虚拟滚动
      style={{ width: "100%" }}
      maxTagCount="responsive"
    >
      {options.map(opt => (
        <Select.Option key={opt.id} value={opt.id}>
          {renderKBOption(opt)}
        </Select.Option>
      ))}
    </Select>
  );
}
