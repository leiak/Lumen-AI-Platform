// frontend/components/text2sql/index.tsx
// M33 — Text2SQL 智能问数 5 个基础组件 (T28)
// Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §6.2
"use client";

import { useState } from "react";
import {
  Button,
  Card,
  Drawer,
  Empty,
  Input,
  List,
  Progress,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import { CopyOutlined, QuestionCircleOutlined } from "@ant-design/icons";
import type {
  Text2SqlAskResponse,
  Text2SqlDetail,
  Text2SqlHistoryItem,
} from "@/types/text2sql";

// --------------------------------------------------------------------------- //
// QuestionInput — textarea + submit + loading state                            //
// --------------------------------------------------------------------------- //

export function QuestionInput({
  onSubmit,
  loading,
  placeholder = "用一句话描述你要查的数据,比如 '客户总数是多少?'",
}: {
  onSubmit: (question: string) => void;
  loading: boolean;
  placeholder?: string;
}) {
  const [text, setText] = useState("");
  return (
    <Space.Compact style={{ width: "100%" }}>
      <Input.TextArea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder}
        autoSize={{ minRows: 2, maxRows: 4 }}
        disabled={loading}
        onPressEnter={(e) => {
          if (e.shiftKey) return;
          if (!text.trim() || loading) return;
          onSubmit(text.trim());
          setText("");
        }}
      />
      <Button
        type="primary"
        loading={loading}
        disabled={!text.trim()}
        onClick={() => {
          if (!text.trim()) return;
          onSubmit(text.trim());
          setText("");
        }}
      >
        提问
      </Button>
    </Space.Compact>
  );
}

// --------------------------------------------------------------------------- //
// SqlDisplay — code block + copy button                                         //
// --------------------------------------------------------------------------- //

export function SqlDisplay({ sql }: { sql: string | null | undefined }) {
  if (!sql) {
    return (
      <Typography.Text type="secondary" italic>
        (无 SQL)
      </Typography.Text>
    );
  }
  const onCopy = () => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(sql).then(
        () => message.success("已复制 SQL"),
        () => message.error("复制失败"),
      );
    }
  };
  return (
    <div
      style={{
        position: "relative",
        background: "#1e1e1e",
        color: "#d4d4d4",
        padding: 12,
        borderRadius: 6,
        fontFamily: "ui-monospace, SFMono-Regular, monospace",
        fontSize: 13,
        whiteSpace: "pre-wrap",
        wordBreak: "break-all",
      }}
    >
      <Button
        size="small"
        icon={<CopyOutlined />}
        onClick={onCopy}
        style={{ position: "absolute", right: 8, top: 8 }}
      >
        复制
      </Button>
      {sql}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// ResultTable — AntD Table with NULL → "—" rendering                           //
// --------------------------------------------------------------------------- //

export function ResultTable({
  columns,
  rows,
  maxRows = 100,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
  maxRows?: number;
}) {
  if (!rows.length) {
    return <Empty description="查询无返回数据" />;
  }
  const display = rows.slice(0, maxRows);
  const truncated = rows.length > maxRows;
  const antdCols = columns.map((c) => ({
    title: c,
    dataIndex: c,
    key: c,
    render: (v: unknown) => (v == null ? "—" : String(v)),
    ellipsis: true,
  }));
  return (
    <>
      <Table
        size="small"
        rowKey={(_, idx) => String(idx)}
        columns={antdCols}
        dataSource={display}
        pagination={{ pageSize: 10, showSizeChanger: false }}
        scroll={{ x: true }}
      />
      {truncated && (
        <Typography.Text type="secondary" italic style={{ display: "block", marginTop: 8 }}>
          (前 {maxRows} 行已显示,共 {rows.length} 行)
        </Typography.Text>
      )}
    </>
  );
}

// --------------------------------------------------------------------------- //
// ExplanationCard — explanation + confidence Progress ring + retry Tag          //
// --------------------------------------------------------------------------- //

export function ExplanationCard({
  explanation,
  confidence,
  attempts,
  rowCount,
}: {
  explanation: string | null | undefined;
  confidence: number | null | undefined;
  attempts?: number;
  rowCount?: number | null;
}) {
  const pct = confidence == null ? null : Math.round(confidence * 100);
  return (
    <Card
      size="small"
      title="AI 解读"
      extra={
        <Space>
          {attempts != null && attempts > 1 && (
            <Tag color="orange">{attempts} 次尝试</Tag>
          )}
          {pct != null && (
            <Tooltip title="LLM 报告的置信度,0-1 区间">
              <Progress
                type="circle"
                size={32}
                percent={pct}
                format={(p) => `${p}%`}
              />
            </Tooltip>
          )}
        </Space>
      }
    >
      <Typography.Paragraph style={{ marginBottom: 0 }}>
        {explanation || "(无解读)"}
      </Typography.Paragraph>
      {rowCount != null && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {rowCount} 行结果
        </Typography.Text>
      )}
    </Card>
  );
}

// --------------------------------------------------------------------------- //
// HistoryList — AntD List + status Tag + click to open detail                  //
// --------------------------------------------------------------------------- //

export function HistoryList({
  items,
  onSelect,
  loading,
  selectedId,
}: {
  items: Text2SqlHistoryItem[];
  onSelect: (item: Text2SqlHistoryItem) => void;
  loading: boolean;
  selectedId?: number;
}) {
  if (!loading && items.length === 0) {
    return <Empty description="暂无历史查询" />;
  }
  return (
    <List
      loading={loading}
      dataSource={items}
      renderItem={(item) => {
        const isSelected = selectedId === item.id;
        return (
          <List.Item
            onClick={() => onSelect(item)}
            style={{
              cursor: "pointer",
              padding: "12px 16px",
              background: isSelected ? "#e6f4ff" : undefined,
              borderRadius: 4,
              marginBottom: 4,
            }}
          >
            <List.Item.Meta
              title={
                <Space>
                  <Tag color={statusColor(item.status)}>{item.status}</Tag>
                  <Typography.Text strong>{item.question_preview}</Typography.Text>
                </Space>
              }
              description={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {item.row_count != null && <>{item.row_count} 行 · </>}
                  {item.attempts > 1 && <>{item.attempts} 次 · </>}
                  {new Date(item.created_at).toLocaleString("zh-CN")}
                </Typography.Text>
              }
            />
          </List.Item>
        );
      }}
    />
  );
}

export function statusColor(status: string): string {
  switch (status) {
    case "success": return "green";
    case "rejected": return "orange";
    case "failed": return "red";
    case "pending":
    case "generating":
    case "executing":
    case "explaining":
      return "blue";
    default: return "default";
  }
}

// --------------------------------------------------------------------------- //
// HistoryDetailDrawer — shows a historical query's full content                 //
// --------------------------------------------------------------------------- //

export function HistoryDetailDrawer({
  detail,
  open,
  onClose,
}: {
  detail: Text2SqlDetail | null;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Drawer
      title={detail?.question || "查询详情"}
      placement="right"
      width={720}
      onClose={onClose}
      open={open}
    >
      {detail && (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Card size="small" title="SQL">
            <SqlDisplay sql={detail.generated_sql} />
          </Card>
          <Card size="small" title="结果" extra={
            <Tag color={statusColor(detail.status)}>
              {detail.row_count ?? 0} 行
              {detail.truncated ? " (已截断)" : ""}
            </Tag>
          }>
            <ResultTable
              columns={detail.columns}
              rows={detail.rows}
            />
          </Card>
          <ExplanationCard
            explanation={detail.explanation}
            confidence={detail.confidence != null ? detail.confidence / 100 : null}
            attempts={detail.attempts}
            rowCount={detail.row_count}
          />
          {detail.error_message && (
            <Card size="small" title="错误">
              <Typography.Text type="danger">{detail.error_message}</Typography.Text>
            </Card>
          )}
        </Space>
      )}
    </Drawer>
  );
}
