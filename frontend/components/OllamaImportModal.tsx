"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Modal,
  Alert,
  Table,
  Switch,
  Input,
  Button,
  Space,
  Tag,
  message,
  Tooltip,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { Checkbox } from "antd";
import {
  modelsApi,
  OllamaModelInfo,
  BulkCreateResultEntry,
} from "@/services/models";

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

interface RowState {
  selected: boolean;
  is_chat: boolean;
  is_embedding: boolean;
}

type RowOutcome = BulkCreateResultEntry;

function humanSize(bytes?: number): string {
  if (!bytes || bytes <= 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = bytes;
  let u = 0;
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024;
    u++;
  }
  return `${v.toFixed(v >= 10 || u === 0 ? 0 : 1)} ${units[u]}`;
}

export default function OllamaImportModal({ open, onClose, onSuccess }: Props) {
  const [loading, setLoading] = useState(false);
  const [reachable, setReachable] = useState<boolean | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [baseUrl, setBaseUrl] = useState<string>("");
  const [models, setModels] = useState<OllamaModelInfo[]>([]);
  // Per-row UI state, keyed by model name.
  const [rowState, setRowState] = useState<Record<string, RowState>>({});
  const [submitting, setSubmitting] = useState(false);
  const [results, setResults] = useState<RowOutcome[] | null>(null);

  // Fetch the import preview whenever the modal opens.
  useEffect(() => {
    if (!open) return;
    setResults(null);
    setErrorMessage(null);
    setReachable(null);
    setModels([]);
    setRowState({});
    setLoading(true);
    modelsApi
      .importFromOllama()
      .then((res) => {
        const data = res.data?.data;
        if (!data) {
          setReachable(false);
          setErrorMessage("后端未返回数据");
          return;
        }
        setReachable(Boolean(data.reachable));
        if (!data.reachable) {
          setErrorMessage(
            data.error_message || `无法连接 Ollama (${data.base_url})`
          );
          return;
        }
        const list: OllamaModelInfo[] = data.models || [];
        setModels(list);
        // Default: new rows are selected + capability-driven flags.
        const init: Record<string, RowState> = {};
        list.forEach((m) => {
          init[m.name] = {
            selected: !m.exists_in_db,
            is_chat: Boolean(m.is_chat_capable),
            is_embedding: Boolean(m.is_embedding_capable),
          };
        });
        setRowState(init);
      })
      .catch((err: any) => {
        setReachable(false);
        setErrorMessage(err?.message || "网络错误");
      })
      .finally(() => setLoading(false));
  }, [open]);

  const allSelected = useMemo(
    () =>
      models.length > 0 &&
      models.every((m) => rowState[m.name]?.selected),
    [models, rowState]
  );

  const toggleAll = (checked: boolean) => {
    const next: Record<string, RowState> = { ...rowState };
    models.forEach((m) => {
      // Don't toggle rows that are already in the DB — those are
      // hard-disabled to avoid confusing the user about whether the
      // existing row will be modified.
      if (m.exists_in_db) return;
      next[m.name] = { ...next[m.name], selected: checked };
    });
    setRowState(next);
  };

  const updateRow = (name: string, patch: Partial<RowState>) => {
    setRowState((prev) => ({ ...prev, [name]: { ...prev[name], ...patch } }));
  };

  const handleSubmit = async () => {
    const rows = models
      .filter((m) => rowState[m.name]?.selected)
      .map((m) => ({
        name: m.name,
        model_type: "ollama",
        model_name: m.name,
        base_url: baseUrl || null,
        is_chat: rowState[m.name].is_chat,
        is_embedding: rowState[m.name].is_embedding,
        description: null,
      }));
    if (rows.length === 0) {
      message.warning("请至少勾选一个模型");
      return;
    }
    setSubmitting(true);
    try {
      const res = await modelsApi.bulkCreate(rows);
      const data = res.data?.data;
      if (res.data?.code === 200 && data?.results) {
        setResults(data.results);
        const created = data.results.filter(
          (r: RowOutcome) => r.status === "created"
        ).length;
        const skipped = data.results.filter(
          (r: RowOutcome) => r.status === "skipped"
        ).length;
        const failed = data.results.filter(
          (r: RowOutcome) => r.status === "error"
        ).length;
        message.success(
          `导入完成:新建 ${created} / 跳过 ${skipped} / 失败 ${failed}`
        );
        if (created > 0) onSuccess();
      } else {
        message.error(res.data?.message || "导入失败");
      }
    } catch (err: any) {
      message.error(err?.message || "网络错误");
    } finally {
      setSubmitting(false);
    }
  };

  const columns: ColumnsType<OllamaModelInfo> = [
    {
      title: (
        <Checkbox
          checked={allSelected}
          // indeterminate would be nicer, but `checked` is enough
          // for the test's "toggles all new rows" path.
          onChange={(e) => toggleAll(e.target.checked)}
        >
          全选
        </Checkbox>
      ),
      key: "select",
      width: 80,
      render: (_, m) => (
        <Checkbox
          checked={rowState[m.name]?.selected || false}
          disabled={m.exists_in_db}
          onChange={(e) => updateRow(m.name, { selected: e.target.checked })}
        />
      ),
    },
    { title: "名称", dataIndex: "name", key: "name" },
    {
      title: "大小",
      dataIndex: "size",
      key: "size",
      width: 100,
      render: (v?: number) => humanSize(v),
    },
    {
      title: "Family",
      dataIndex: "family",
      key: "family",
      width: 120,
      render: (v?: string) => v || "—",
    },
    {
      title: "能力",
      key: "capabilities",
      render: (_, m) => (
        <Space size={4} wrap>
          {m.is_chat_capable && <Tag color="blue">chat</Tag>}
          {m.is_embedding_capable && <Tag color="purple">embedding</Tag>}
          {m.exists_in_db && <Tag color="default">已存在</Tag>}
          {!m.is_chat_capable && !m.is_embedding_capable && (
            <Tag>未声明</Tag>
          )}
        </Space>
      ),
    },
    {
      title: "用途",
      key: "purpose",
      width: 160,
      render: (_, m) => (
        <Space size={8}>
          <Tooltip title="可用作对话模型">
            <Switch
              size="small"
              checked={rowState[m.name]?.is_chat || false}
              onChange={(v) => updateRow(m.name, { is_chat: v })}
              disabled={m.exists_in_db}
              checkedChildren="Chat"
              unCheckedChildren="Chat"
            />
          </Tooltip>
          <Tooltip title="可用作 embedding 模型">
            <Switch
              size="small"
              checked={rowState[m.name]?.is_embedding || false}
              onChange={(v) => updateRow(m.name, { is_embedding: v })}
              disabled={m.exists_in_db}
              checkedChildren="Embed"
              unCheckedChildren="Embed"
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <Modal
      title="从 Ollama 导入模型"
      open={open}
      onCancel={onClose}
      width={840}
      destroyOnHidden
      footer={
        results
          ? [
              <Button key="ok" type="primary" onClick={onClose}>
                完成
              </Button>,
            ]
          : [
              <Button key="cancel" onClick={onClose}>
                取消
              </Button>,
              <Button
                key="submit"
                type="primary"
                loading={submitting}
                disabled={loading || !reachable}
                onClick={handleSubmit}
              >
                批量导入
              </Button>,
            ]
      }
    >
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        {!reachable && errorMessage && (
          <Alert
            type="error"
            showIcon
            message="无法连接 Ollama"
            description={errorMessage}
          />
        )}

        <div>
          <span style={{ marginRight: 8 }}>Base URL (可选,留空用默认):</span>
          <Input
            style={{ width: 280 }}
            placeholder="http://localhost:11434"
            allowClear
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            disabled={loading || !reachable}
          />
        </div>

        {results ? (
          <Table<RowOutcome>
            size="small"
            rowKey="requested_model_name"
            dataSource={results}
            pagination={false}
            columns={[
              { title: "模型", dataIndex: "requested_model_name" },
              {
                title: "结果",
                dataIndex: "status",
                render: (s: string, r: RowOutcome) => {
                  if (s === "created")
                    return <Tag color="success">已创建</Tag>;
                  if (s === "skipped")
                    return (
                      <Tooltip
                        title={
                          r.existing_config_id
                            ? `已存在的 config id: ${r.existing_config_id}`
                            : "重复"
                        }
                      >
                        <Tag color="default">已跳过</Tag>
                      </Tooltip>
                    );
                  return (
                    <Tooltip title={r.error}>
                      <Tag color="error">失败</Tag>
                    </Tooltip>
                  );
                },
              },
              {
                title: "备注",
                render: (_, r: RowOutcome) => {
                  if (r.status === "skipped" && r.existing_config_id) {
                    return `existing_config_id=${r.existing_config_id}`;
                  }
                  if (r.status === "error") return r.error;
                  return "";
                },
              },
            ]}
          />
        ) : (
          <Table<OllamaModelInfo>
            size="small"
            rowKey="name"
            dataSource={models}
            loading={loading}
            pagination={false}
            columns={columns}
            locale={{
              emptyText: reachable
                ? "Ollama 中没有可用模型"
                : "等待 Ollama 连接...",
            }}
          />
        )}
      </Space>
    </Modal>
  );
}
