// frontend/app/dashboard/text2sql/page.tsx
// M33 — 智能问数 主页面 (T30)
//
// 4 个 Tab: 提问 / 历史 / 数据源管理 / Schema 浏览
// Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §6.2
"use client";

import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Space,
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";
import { ReloadOutlined, DatabaseOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { text2SqlApi } from "@/services/text2sql";
import type { Text2SqlDetail, Text2SqlHistoryItem } from "@/types/text2sql";
import {
  ExplanationCard,
  HistoryDetailDrawer,
  HistoryList,
  QuestionInput,
  ResultTable,
  SqlDisplay,
  statusColor,
} from "@/components/text2sql";
import { DataSourceManager } from "@/components/text2sql/DataSourceManager";

export default function Text2SqlPage() {
  const qc = useQueryClient();
  const [dataSourceId, setDataSourceId] = useState<number | null>(null);
  const [askResult, setAskResult] = useState<{
    query_id: number;
    status: string;
    generated_sql?: string | null;
    columns: string[];
    rows: Record<string, unknown>[];
    row_count: number;
    truncated: boolean;
    explanation?: string | null;
    confidence?: number | null;
    attempts: number;
    error_type?: string | null;
    error_message?: string | null;
    duration_ms?: number | null;
  } | null>(null);
  const [askLoading, setAskLoading] = useState(false);
  const [selectedHistoryId, setSelectedHistoryId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Data sources list
  const { data: dsList, isLoading: dsLoading } = useQuery({
    queryKey: ["text2sql-datasources"],
    queryFn: () => text2SqlApi.listDataSources({ page_size: 100 }),
  });
  const sources = dsList?.items ?? [];
  const activeSource =
    dataSourceId != null
      ? sources.find((s) => s.id === dataSourceId)
      : sources[0];
  const effectiveSourceId = activeSource?.id ?? null;

  // History list
  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ["text2sql-history"],
    queryFn: () => text2SqlApi.listHistory({ page_size: 50 }),
  });

  // Selected history detail
  const { data: selectedDetail } = useQuery({
    queryKey: ["text2sql-history-detail", selectedHistoryId],
    queryFn: () => text2SqlApi.getHistory(selectedHistoryId!),
    enabled: selectedHistoryId != null,
  });

  // Schema
  const { data: schema, isLoading: schemaLoading } = useQuery({
    queryKey: ["text2sql-schema", effectiveSourceId],
    queryFn: () => text2SqlApi.getSchema(effectiveSourceId!),
    enabled: effectiveSourceId != null,
  });

  const onAsk = async (question: string) => {
    if (effectiveSourceId == null) {
      message.error("请先选择数据源");
      return;
    }
    setAskLoading(true);
    setAskResult(null);
    try {
      const res = await text2SqlApi.ask({
        data_source_id: effectiveSourceId,
        question,
        async_run: false,
      });
      setAskResult(res);
      // Refresh history on success
      if (res.status === "success") {
        qc.invalidateQueries({ queryKey: ["text2sql-history"] });
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "查询失败";
      message.error(msg);
    } finally {
      setAskLoading(false);
    }
  };

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: "0 auto" }}>
      <Space style={{ marginBottom: 16 }} align="center">
        <DatabaseOutlined style={{ fontSize: 20, color: "#1677ff" }} />
        <Typography.Title level={3} style={{ margin: 0 }}>
          智能问数
        </Typography.Title>
        <Tag color="blue">M33</Tag>
      </Space>

      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <span>数据源:</span>
          {dsLoading ? (
            <Tag>加载中…</Tag>
          ) : sources.length === 0 ? (
            <Alert
              type="warning"
              message="尚无数据源,请到「数据源管理」标签新建"
              showIcon
            />
          ) : (
            <Space wrap>
              {sources.map((s) => (
                <Button
                  key={s.id}
                  type={
                    (dataSourceId ?? sources[0]?.id) === s.id
                      ? "primary"
                      : "default"
                  }
                  onClick={() => {
                    setDataSourceId(s.id);
                    setAskResult(null);
                  }}
                >
                  {s.name}
                </Button>
              ))}
            </Space>
          )}
        </Space>
      </Card>

      <Tabs
        defaultActiveKey="ask"
        items={[
          {
            key: "ask",
            label: "提问",
            children: (
              <Card>
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                  <QuestionInput onSubmit={onAsk} loading={askLoading} />
                  {!activeSource && (
                    <Alert
                      type="info"
                      message="请先选择数据源"
                      showIcon
                    />
                  )}
                  {askResult && (
                    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                      {askResult.status === "success" ? (
                        <>
                          <Card
                            size="small"
                            title="SQL"
                            extra={
                              <Tag color="green">
                                {askResult.row_count} 行
                                {askResult.truncated ? " (已截断)" : ""}
                              </Tag>
                            }
                          >
                            <SqlDisplay sql={askResult.generated_sql} />
                          </Card>
                          <Card size="small" title="结果">
                            <ResultTable
                              columns={askResult.columns}
                              rows={askResult.rows}
                            />
                          </Card>
                          <ExplanationCard
                            explanation={askResult.explanation}
                            confidence={
                              askResult.confidence != null
                                ? askResult.confidence / 100
                                : null
                            }
                            attempts={askResult.attempts}
                            rowCount={askResult.row_count}
                          />
                        </>
                      ) : (
                        <Alert
                          type="error"
                          showIcon
                          message={`查询${askResult.status === "rejected" ? "被拒绝" : "失败"}`}
                          description={
                            <Space direction="vertical">
                              <span>类型: {askResult.error_type}</span>
                              <span>{askResult.error_message}</span>
                            </Space>
                          }
                        />
                      )}
                    </Space>
                  )}
                </Space>
              </Card>
            ),
          },
          {
            key: "history",
            label: "历史",
            children: (
              <Card
                title={
                  <Space>
                    <span>历史查询</span>
                    <Button
                      size="small"
                      icon={<ReloadOutlined />}
                      onClick={() =>
                        qc.invalidateQueries({ queryKey: ["text2sql-history"] })
                      }
                    >
                      刷新
                    </Button>
                  </Space>
                }
              >
                <HistoryList
                  items={history?.items ?? []}
                  loading={historyLoading}
                  onSelect={(item: Text2SqlHistoryItem) => {
                    setSelectedHistoryId(item.id);
                    setDrawerOpen(true);
                  }}
                  selectedId={selectedHistoryId ?? undefined}
                />
              </Card>
            ),
          },
          {
            key: "datasources",
            label: "数据源管理",
            children: (
              <Card>
                <DataSourceManager />
              </Card>
            ),
          },
          {
            key: "schema",
            label: "Schema 浏览",
            children: (
              <Card>
                {!effectiveSourceId ? (
                  <Empty description="请先选择数据源" />
                ) : schemaLoading ? (
                  <Typography.Text type="secondary">加载中…</Typography.Text>
                ) : schema ? (
                  <>
                    <Typography.Title level={5}>
                      {schema.db_name} · {schema.table_count} 张表
                    </Typography.Title>
                    <pre
                      style={{
                        background: "#fafafa",
                        padding: 12,
                        borderRadius: 6,
                        maxHeight: 600,
                        overflow: "auto",
                        fontSize: 12,
                      }}
                    >
                      {schema.schema_text}
                    </pre>
                  </>
                ) : null}
              </Card>
            ),
          },
        ]}
      />
      <HistoryDetailDrawer
        detail={selectedDetail ?? null}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}
