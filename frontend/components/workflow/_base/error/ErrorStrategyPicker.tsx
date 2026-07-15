"use client";
import { Radio, Input, Alert } from "antd";
import { useState } from "react";
import type { ErrorStrategy } from "./types";

interface Props {
  value: ErrorStrategy | null;
  onChange: (strategy: ErrorStrategy, defaultValue?: Record<string, unknown>) => void;
  defaultValue?: Record<string, unknown> | null;
}

export function ErrorStrategyPicker({ value, onChange, defaultValue }: Props) {
  const [text, setText] = useState(
    defaultValue ? JSON.stringify(defaultValue, null, 2) : ""
  );
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <Radio.Group
        value={value ?? "fail_branch"}
        onChange={(e) => onChange(e.target.value as ErrorStrategy, defaultValue ?? undefined)}
      >
        <Radio.Button value="fail_branch">失败时停止分支</Radio.Button>
        <Radio.Button value="default_value">使用默认值</Radio.Button>
        <Radio.Button value="ignore">忽略错误</Radio.Button>
      </Radio.Group>
      {value === "default_value" && (
        <>
          <Alert
            type="info"
            showIcon
            message="默认值 JSON(失败时返回给下游节点)"
            style={{ marginTop: 8 }}
          />
          <Input.TextArea
            rows={4}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              try {
                const parsed = JSON.parse(e.target.value);
                onChange("default_value", parsed);
              } catch {
                /* ignore parse error, user is typing */
              }
            }}
            placeholder='{"answer": "未知"}'
          />
        </>
      )}
    </div>
  );
}
