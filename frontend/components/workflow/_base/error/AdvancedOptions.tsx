"use client";
import { Collapse } from "antd";
import { ErrorStrategyPicker } from "./ErrorStrategyPicker";
import { RetryConfigForm } from "./RetryConfigForm";
import { TimeoutInput } from "./TimeoutInput";
import type { ErrorStrategy, RetryConfig } from "./types";

interface AdvancedConfig {
  error_strategy?: ErrorStrategy | null;
  default_value?: Record<string, unknown> | null;
  retry_config?: RetryConfig | null;
  timeout?: number | null;
}

interface Props {
  config: AdvancedConfig;
  onChange: (patch: Partial<AdvancedConfig>) => void;
}

export function AdvancedOptions({ config, onChange }: Props) {
  return (
    <Collapse
      ghost
      items={[
        {
          key: "adv",
          label: "高级选项(错误处理 / 重试 / 超时)",
          children: (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div>
                <div style={{ marginBottom: 4, fontSize: 14, color: "#595959" }}>
                  错误处理策略
                </div>
                <ErrorStrategyPicker
                  value={config.error_strategy ?? null}
                  defaultValue={config.default_value ?? null}
                  onChange={(s, dv) =>
                    onChange({ error_strategy: s, default_value: dv ?? null })
                  }
                />
              </div>
              <div>
                <div style={{ marginBottom: 4, fontSize: 14, color: "#595959" }}>
                  重试配置
                </div>
                <RetryConfigForm
                  value={config.retry_config ?? null}
                  onChange={(rc) => onChange({ retry_config: rc })}
                />
              </div>
              <div>
                <div style={{ marginBottom: 4, fontSize: 14, color: "#595959" }}>
                  超时
                </div>
                <TimeoutInput
                  value={config.timeout ?? null}
                  onChange={(t) => onChange({ timeout: t })}
                />
              </div>
            </div>
          ),
        },
      ]}
    />
  );
}
