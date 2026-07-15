"use client";
import { InputNumber, Form } from "antd";
import { DEFAULT_TIMEOUT_SECONDS } from "./types";

interface Props {
  value: number | null;
  onChange: (seconds: number | null) => void;
}

export function TimeoutInput({ value, onChange }: Props) {
  return (
    <Form.Item label="超时(秒)">
      <InputNumber
        min={1}
        max={300}
        value={value ?? DEFAULT_TIMEOUT_SECONDS}
        onChange={(v) => onChange(v == null ? null : Number(v))}
        placeholder="默认 30 秒"
      />
    </Form.Item>
  );
}
