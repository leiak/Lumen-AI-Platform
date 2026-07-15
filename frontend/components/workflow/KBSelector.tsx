"use client";

import { useEffect, useMemo, useState } from "react";
import { Select, Alert, Space } from "antd";
import { fetchAllKBOptions, type KBOption } from "./kb-list";

const MISSING_VALUE = "__missing__";

export interface KBSelectorProps {
  value: number | null;
  kbNameCache: string;
  onChange: (kbId: number | null, kbName: string) => void;
}

export function KBSelector({ value, kbNameCache, onChange }: KBSelectorProps) {
  const [kbs, setKbs] = useState<KBOption[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refetch = async () => {
    try {
      const opts = await fetchAllKBOptions();
      setKbs(opts);
      // 旧实现里 code != 200 时把 res.data.message 塞到 loadError;
      // fetchAllKBOptions 现在吞掉非 200 返空数组,所以用通用文案。
      setLoadError(opts.length === 0 ? "加载失败" : null);
    } catch (err: any) {
      setLoadError(err?.message ?? "网络错误");
    }
  };

  useEffect(() => {
    refetch();
  }, []);

  // Spec drift note: the P2 plan's `knowledgeBaseApi.list({ active: true })`
  // and `is_active: boolean` don't match the real backend, which exposes
  // `status: "active" | "inactive"`. We filter client-side as a defensive
  // measure (mirroring ToolSelector's `is_enabled` filter).
  const activeKBs = useMemo(
    () => (kbs ?? []).filter((k) => k.status === "active"),
    [kbs]
  );

  const isMissing =
    value != null && !activeKBs.some((k) => k.id === value);

  const selectedValue: string | undefined = useMemo(() => {
    if (value == null) return undefined;
    const hit = activeKBs.find((k) => k.id === value);
    return hit ? String(hit.id) : MISSING_VALUE;
  }, [value, activeKBs]);

  const options = useMemo(() => {
    const opts = activeKBs.map((k) => ({
      label: k.name,
      value: String(k.id),
    }));
    if (isMissing) {
      const label = kbNameCache
        ? `⚠️ (已删除) ${kbNameCache}`
        : "⚠️ (已删除)";
      opts.push({ label, value: MISSING_VALUE });
    }
    return opts;
  }, [activeKBs, isMissing, kbNameCache]);

  const handleChange = (v: string) => {
    if (v === MISSING_VALUE) {
      // Re-clicking the missing sentinel: keep the cached value so the user
      // can re-pick from the dropdown.
      onChange(value, kbNameCache);
      return;
    }
    const k = activeKBs.find((x) => x.id === Number(v));
    if (!k) return;
    onChange(k.id, k.name);
  };

  if (loadError) {
    return (
      <Space direction="vertical" style={{ width: "100%" }}>
        <Alert
          type="error"
          showIcon
          message="知识库数据加载失败,请刷新重试"
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
        placeholder="选择知识库"
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
          原知识库已失效 ({kbNameCache || "未知"})。请重新选择或在知识库管理中重建。
        </div>
      )}
    </>
  );
}

export default KBSelector;
