"use client";

// frontend/components/eval/RunProgressBar.tsx
// M37.2 — 评测进度条 + 状态 chip。
//
// 进度 = completed_items / total_items。状态 chip 显示 pending / running /
// completed / failed / cancelled,前端 1s 轮询一次。
// 用 antd Progress(线性) + Tag(状态颜色),风格跟 dashboard / videos 一致。

import { Progress, Space, Tag } from "antd";
import type { EvalRunStatus } from "@/types/eval_run";

interface RunProgressBarProps {
  status: EvalRunStatus;
  completed: number;
  total: number;
  /** 失败信息(失败状态时显示) */
  errorMessage?: string | null;
}

const STATUS_LABEL: Record<EvalRunStatus, string> = {
  pending: "等待中 / Pending",
  running: "运行中 / Running",
  completed: "已完成 / Completed",
  failed: "失败 / Failed",
  cancelled: "已取消 / Cancelled",
};

const STATUS_COLOR: Record<EvalRunStatus, string> = {
  pending: "default",
  running: "processing",
  completed: "success",
  failed: "error",
  cancelled: "warning",
};

export default function RunProgressBar({
  status,
  completed,
  total,
  errorMessage,
}: RunProgressBarProps) {
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

  // 终态(cancelled / failed / completed)不再 progress 动,显示纯状态标签
  if (status !== "pending" && status !== "running") {
    return (
      <Space size="small" direction="vertical" style={{ width: "100%" }}>
        <Tag color={STATUS_COLOR[status]}>{STATUS_LABEL[status]}</Tag>
        {status === "failed" && errorMessage && (
          <span style={{ color: "#cf1322", fontSize: 12 }}>
            {errorMessage}
          </span>
        )}
      </Space>
    );
  }

  return (
    <Space size="small" direction="vertical" style={{ width: "100%" }}>
      <Tag color={STATUS_COLOR[status]}>{STATUS_LABEL[status]}</Tag>
      <Progress
        percent={pct}
        size="small"
        status={status === "running" ? "active" : "normal"}
        format={() => `${completed} / ${total}`}
      />
    </Space>
  );
}
