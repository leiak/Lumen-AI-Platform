"use client";
import { InputNumber, Form } from "antd";
import { DEFAULT_RETRY, type RetryConfig } from "./types";

interface Props {
  value: RetryConfig | null;
  onChange: (cfg: RetryConfig) => void;
}

export function RetryConfigForm({ value, onChange }: Props) {
  const cfg: RetryConfig = value ?? DEFAULT_RETRY;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
      <Form.Item label="最大重试次数">
        <InputNumber
          min={0}
          max={10}
          value={cfg.max_retries}
          onChange={(v) => onChange({ ...cfg, max_retries: Number(v ?? 0) })}
        />
      </Form.Item>
      <Form.Item label="重试间隔(秒)">
        <InputNumber
          min={0.1}
          max={60}
          step={0.1}
          value={cfg.retry_interval}
          onChange={(v) => onChange({ ...cfg, retry_interval: Number(v ?? 1.0) })}
        />
      </Form.Item>
    </div>
  );
}
