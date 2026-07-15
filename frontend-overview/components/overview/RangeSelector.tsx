"use client";
import { Segmented, Button, Space, Tooltip } from "antd";
import { PauseOutlined, ReloadOutlined, PlayCircleOutlined } from "@ant-design/icons";
import { useScreenStore } from "@/store/screen";
import type { ScreenRange } from "@/services/screen";

const RANGES: { label: string; value: ScreenRange }[] = [
  { label: "1h", value: "1h" },
  { label: "24h", value: "24h" },
  { label: "7d", value: "7d" },
  { label: "30d", value: "30d" },
];

const INTERVALS = [
  { label: "5s", value: 5000 },
  { label: "10s", value: 10000 },
  { label: "30s", value: 30000 },
  { label: "关", value: 0 },
];

export function RangeSelector() {
  const range = useScreenStore((s) => s.range);
  const intervalMs = useScreenStore((s) => s.intervalMs);
  const paused = useScreenStore((s) => s.paused);
  const setRange = useScreenStore((s) => s.setRange);
  const setInterval = useScreenStore((s) => s.setInterval);
  const togglePaused = useScreenStore((s) => s.togglePaused);

  return (
    <Space>
      <Segmented options={RANGES} value={range} onChange={(v) => setRange(v as ScreenRange)} />
      <Segmented
        options={INTERVALS}
        value={intervalMs}
        onChange={(v) => setInterval(v as number)}
      />
      <Tooltip title={paused ? "继续轮询" : "暂停轮询"}>
        <Button
          icon={paused ? <PlayCircleOutlined /> : <PauseOutlined />}
          onClick={togglePaused}
        />
      </Tooltip>
      <Button icon={<ReloadOutlined />} onClick={() => window.location.reload()}>刷新</Button>
    </Space>
  );
}
