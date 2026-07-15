// frontend/components/workflow/designer/RunResultPanel.tsx
//
// M30c: per-node Timeline view. The pre-M30c implementation only
// showed LLM nodes' `output_values.response` (filtered by
// `value.output_values.response` truthy). Code/HTTP/KB/Tool/PE/QC/VA
// outputs were completely hidden — users only ever saw the status
// tag and (sometimes) the final output. After M30c the panel renders
// one row per node, in execution order, with status / duration /
// error highlight, and an expandable JSON view of input_data +
// output_data.
//
// Two data sources are merged when both are present:
//   1. result.output_data.results — the executor's per-node in-memory
//      result map (always available right after /run)
//   2. nodeRuns — the M30a `WorkflowNodeRun` rows fetched separately
//      from /runs/{id}/nodes (durable on disk; survives page reload)
//
// The timeline prefers the M30a rows when present (they have the
// canonical execution_order + duration), and falls back to the
// in-memory results otherwise.
import { useMemo } from "react";
import { Card, Space, Tag, Empty, Spin, Alert, Button, Collapse, Tooltip } from "antd";
import { ThunderboltOutlined, ClockCircleOutlined, WarningOutlined } from "@ant-design/icons";
import { extractAIMessageContent } from "@/components/workflow/_base/aimessage";
import type { WorkflowNodeRun } from "@/services/workflow";

export interface RunResultPanelProps {
  result: any | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  /**
   * M30c: optional M30a `WorkflowNodeRun` rows. When provided, the
   * timeline uses these for execution_order / status / duration
   * (durable, persisted). When null, the panel falls back to
   * `result.output_data.results` (in-memory, ephemeral).
   */
  nodeRuns?: WorkflowNodeRun[] | null;
}

const statusColor = (status: string) =>
  status === "completed"
    ? "green"
    : status === "failed"
      ? "red"
      : status === "running"
        ? "blue"
        : status === "cancelled"
          ? "default"
          : "default";

const fmtDuration = (started: string | null | undefined, finished: string | null | undefined) => {
  if (!started || !finished) return "-";
  const ms = new Date(finished).getTime() - new Date(started).getTime();
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`;
  return `${(ms / 60_000).toFixed(2)} min`;
};

interface TimelineRow {
  key: string;
  nodeId: string;
  nodeType: string;
  status: string;
  durationLabel: string;
  inputData: Record<string, any> | null;
  outputData: Record<string, any> | null;
  errorMessage: string | null;
  executionOrder: number | null;
}

export function RunResultPanel({
  result,
  loading,
  error,
  onClose,
  nodeRuns,
}: RunResultPanelProps) {
  const innerOutput = (result as any)?.output_data ?? null;

  // M30c: build the timeline. We prefer nodeRuns (M30a persisted
  // rows) when provided, and fall back to result.output_data.results
  // (executor in-memory). Each row carries status / duration / input
  // / output / error so the UI can render the full state.
  const timeline: TimelineRow[] = useMemo(() => {
    if (nodeRuns && nodeRuns.length > 0) {
      return nodeRuns
        .slice()
        .sort((a, b) => {
          const ao = a.execution_order ?? 1e9;
          const bo = b.execution_order ?? 1e9;
          if (ao !== bo) return ao - bo;
          return a.id - b.id;
        })
        .map((nr) => ({
          key: `nr-${nr.id}`,
          nodeId: nr.node_id,
          nodeType: nr.node_type,
          status: nr.status,
          durationLabel: fmtDuration(nr.started_at, nr.finished_at),
          inputData: (nr.input_data as Record<string, any> | null) ?? null,
          outputData: (nr.output_data as Record<string, any> | null) ?? null,
          errorMessage: nr.error_message ?? null,
          executionOrder: nr.execution_order ?? null,
        }));
    }
    if (innerOutput?.results) {
      // No nodeRuns provided — synthesize from output_data.
      return Object.entries(innerOutput.results).map(
        ([nodeId, value]: [string, any], idx) => {
          // M30c: best-effort LLM detection when only output_values is
          // available. The pre-M30c panel only showed nodes whose
          // output_values had a `.response` field, so users saw LLM
          // cards but nothing else. Keep that visibility for LLM
          // nodes; surface all other nodes too with their raw
          // output_values.
          const ov = (value?.output_values ?? {}) as Record<string, any>;
          const inferredType =
            value?.node_type ??
            value?.type ??
            // LLM signature: a `.response` field with a string value.
            (typeof ov.response === "string" ? "llm" : "unknown");
          return {
            key: `mem-${nodeId}`,
            nodeId,
            nodeType: inferredType,
            status: value?.error ? "failed" : "completed",
            durationLabel: "-",
            inputData: null,
            outputData: ov,
            errorMessage: value?.error ?? null,
            executionOrder: idx,
          };
        }
      );
    }
    return [];
  }, [nodeRuns, innerOutput]);

  // Final output fallback (when no per-node output is useful).
  const finalValue = innerOutput?.final_output?.value ?? null;

  // LLM convenience: pick the response text from any LLM-shaped
  // output so the user can copy it without expanding the JSON.
  const llmResponses = useMemo(() => {
    const out: Array<{ nodeId: string; text: string }> = [];
    for (const row of timeline) {
      const response = row.outputData?.response;
      if (response && typeof response === "string") {
        const text = extractAIMessageContent(response);
        if (text) out.push({ nodeId: row.nodeId, text });
      }
    }
    return out;
  }, [timeline]);

  return (
    <Card
      size="small"
      style={{ marginTop: 16, maxHeight: 480, overflow: "auto" }}
      title={
        <Space>
          <ThunderboltOutlined />
          <span>运行结果</span>
          {nodeRuns && nodeRuns.length > 0 && (
            <Tag color="blue" style={{ marginLeft: 4 }}>
              M30a timeline
            </Tag>
          )}
        </Space>
      }
      extra={
        <Button size="small" onClick={onClose}>
          关闭
        </Button>
      }
    >
      {loading && <Spin tip="执行中..." />}
      {error && (
        <Alert type="error" message="执行失败" description={error} showIcon />
      )}
      {!loading && !error && !result && <Empty description="尚未运行" />}

      {!loading && !error && result && (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          {/* Top-level run status. */}
          <div>
            <Tag color={statusColor(result.status)}>{result.status}</Tag>
            {result.error_message && (
              <Tooltip title={result.error_message}>
                <Tag icon={<WarningOutlined />} color="red" style={{ marginLeft: 4 }}>
                  错误
                </Tag>
              </Tooltip>
            )}
          </div>

          {/* Per-node timeline. Empty state hints at the pre-M30c
              legacy behavior. */}
          {timeline.length === 0 && (
            <Empty description="本次执行未触发任何节点" />
          )}

          {timeline.map((row) => {
            const isFailed = row.status === "failed";
            const isLlm = row.nodeType === "llm" || row.nodeType === "agent";
            return (
              <Card
                key={row.key}
                size="small"
                type="inner"
                style={
                  isFailed
                    ? { borderColor: "#ff4d4f", background: "#fff1f0" }
                    : undefined
                }
                title={
                  <Space wrap>
                    <span style={{ fontWeight: 500 }}>{row.nodeType}</span>
                    <Tag>{row.nodeId}</Tag>
                    {row.executionOrder != null && (
                      <Tag color="default">#{row.executionOrder}</Tag>
                    )}
                    <Tag color={statusColor(row.status)}>{row.status}</Tag>
                    {row.durationLabel !== "-" && (
                      <Tooltip title="节点耗时">
                        <Tag icon={<ClockCircleOutlined />}>{row.durationLabel}</Tag>
                      </Tooltip>
                    )}
                    {isLlm && row.outputData?.response && (
                      <Tag color="purple">LLM 响应</Tag>
                    )}
                  </Space>
                }
              >
                {isFailed && row.errorMessage && (
                  <Alert
                    type="error"
                    showIcon
                    message="节点执行失败"
                    description={
                      <pre
                        style={{
                          whiteSpace: "pre-wrap",
                          fontSize: 12,
                          margin: 0,
                        }}
                      >
                        {row.errorMessage}
                      </pre>
                    }
                    style={{ marginBottom: 8 }}
                  />
                )}

                {/* LLM shortcut: render the parsed response text. */}
                {isLlm && row.outputData?.response && (
                  <div style={{ marginBottom: 8 }}>
                    <Tag color="green">Output</Tag>
                    <pre
                      style={{
                        whiteSpace: "pre-wrap",
                        background: "#f6ffed",
                        padding: 6,
                        borderRadius: 4,
                        fontSize: 12,
                        margin: "4px 0 0",
                      }}
                    >
                      {extractAIMessageContent(row.outputData.response)}
                    </pre>
                  </div>
                )}

                {/* Raw JSON for power users. */}
                <Collapse
                  ghost
                  size="small"
                  items={[
                    {
                      key: "io",
                      label: "input / output (JSON)",
                      children: (
                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                          {row.inputData && (
                            <div>
                              <Tag color="blue">input</Tag>
                              <pre
                                style={{
                                  whiteSpace: "pre-wrap",
                                  background: "#fafafa",
                                  padding: 6,
                                  borderRadius: 4,
                                  fontSize: 12,
                                  margin: "4px 0 0",
                                }}
                              >
                                {JSON.stringify(row.inputData, null, 2)}
                              </pre>
                            </div>
                          )}
                          {row.outputData && (
                            <div>
                              <Tag color="green">output</Tag>
                              <pre
                                style={{
                                  whiteSpace: "pre-wrap",
                                  background: "#fafafa",
                                  padding: 6,
                                  borderRadius: 4,
                                  fontSize: 12,
                                  margin: "4px 0 0",
                                }}
                              >
                                {JSON.stringify(row.outputData, null, 2)}
                              </pre>
                            </div>
                          )}
                          {!row.inputData && !row.outputData && (
                            <span style={{ color: "#999", fontSize: 12 }}>
                              无 input / output 数据
                            </span>
                          )}
                        </div>
                      ),
                    },
                  ]}
                />
              </Card>
            );
          })}

          {/* Final-output shortcut (when no useful per-node output). */}
          {timeline.length === 0 && finalValue != null && (
            <div>
              <Tag color="blue">最终输出</Tag>
              <pre
                style={{
                  whiteSpace: "pre-wrap",
                  background: "#e6f4ff",
                  padding: 6,
                  borderRadius: 4,
                  fontSize: 12,
                }}
              >
                {typeof finalValue === "string"
                  ? finalValue
                  : JSON.stringify(finalValue, null, 2)}
              </pre>
            </div>
          )}

          {/* When LLM nodes ran but no other nodes fired (legacy
              case), keep the response text visible. */}
          {timeline.length > 0 && llmResponses.length > 0 && timeline.length === llmResponses.length && timeline.every((r) => r.nodeType !== "agent" && r.nodeType !== "llm") && (
            <div>
              <Tag color="blue">最终输出</Tag>
              <pre
                style={{
                  whiteSpace: "pre-wrap",
                  background: "#e6f4ff",
                  padding: 6,
                  borderRadius: 4,
                  fontSize: 12,
                }}
              >
                {JSON.stringify(finalValue, null, 2)}
              </pre>
            </div>
          )}
        </Space>
      )}
    </Card>
  );
}
