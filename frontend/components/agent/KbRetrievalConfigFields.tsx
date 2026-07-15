"use client";
import { Form, InputNumber, Space } from "antd";

export type KbRetrievalConfigFieldsProps = {
  value?: { top_k: number; rrf_k: number };
  onChange?: (value: { top_k: number; rrf_k: number }) => void;
};

const DEFAULTS = { top_k: 3, rrf_k: 30 };

export function KbRetrievalConfigFields({ value, onChange }: KbRetrievalConfigFieldsProps) {
  const v = value ?? DEFAULTS;
  const update = (patch: Partial<typeof v>) => {
    onChange?.({ ...v, ...patch });
  };

  return (
    <Space size="middle" style={{ width: "100%" }}>
      <Form.Item
        label="top_k"
        tooltip="每个 KB 召回的 chunk 数(1-10)"
        style={{ marginBottom: 0 }}
      >
        <InputNumber
          min={1}
          max={10}
          value={v.top_k}
          onChange={(val) => update({ top_k: val ?? DEFAULTS.top_k })}
        />
      </Form.Item>
      <Form.Item
        label="rrf_k"
        tooltip="RRF 公式常数(10-100),标准 60,我们默认 30"
        style={{ marginBottom: 0 }}
      >
        <InputNumber
          min={10}
          max={100}
          value={v.rrf_k}
          onChange={(val) => update({ rrf_k: val ?? DEFAULTS.rrf_k })}
        />
      </Form.Item>
    </Space>
  );
}
