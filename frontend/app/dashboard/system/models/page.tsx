"use client";

import { useState, useEffect, useMemo } from "react";
import {
  Table,
  Button,
  Space,
  Modal,
  Form,
  Input,
  Select,
  InputNumber,
  Switch,
  message,
  Popconfirm,
  Tag,
  Card,
  Row,
  Col,
  Divider,
  Empty,
  Spin,
  Alert,
  Tooltip,
} from "antd";
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  CheckCircleOutlined,
  LinkOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { modelsApi, ModelConfig } from "@/services/models";
import { knowledgeApi } from "@/services/knowledge";
import type { KnowledgeBase } from "@/types/api";
import OllamaImportModal from "@/components/OllamaImportModal";

const { TextArea } = Input;

export interface ModelProviderOption {
  value: string;
  label: string;
  description: string;
  base_url_hint?: string;
}

// Hardcoded fallback used when the backend `/models/providers/list`
// endpoint is unreachable. The backend is the source of truth — this
// is here purely so the page still renders if the catalog endpoint
// fails. The set MUST stay a subset of the backend's MODEL_PROVIDERS
// to avoid letting admins save configs the loader can't instantiate.
//
// Mirrors `backend/app/core/model_providers.py:MODEL_PROVIDERS` as of
// 2026-06-15 (openai/azure_openai/mistral/groq/grok removed because
// the loader had no real implementations behind them).
const FALLBACK_PROVIDERS: ModelProviderOption[] = [
  { value: "ollama", label: "Ollama (本地)", description: "本地运行的大模型", base_url_hint: "http://localhost:11434" },
  { value: "anthropic", label: "Anthropic", description: "Claude系列模型", base_url_hint: "https://api.anthropic.com" },
  { value: "zhipu", label: "智谱 GLM", description: "国产大模型", base_url_hint: "https://open.bigmodel.cn/api/paas/v4" },
  { value: "minimax", label: "MiniMax", description: "MiniMax 大模型" },
];

export default function ModelsPage() {
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form] = Form.useForm();
  const [pagination, setPagination] = useState({ current: 1, pageSize: 10, total: 0 });

  // Provider catalog (dynamically loaded from /models/providers/list)
  const [providers, setProviders] = useState<ModelProviderOption[]>([]);
  const [providersLoading, setProvidersLoading] = useState(true);
  const [providersError, setProvidersError] = useState<string | null>(null);

  // Type filter for the table (re-uses the catalog)
  const [typeFilter, setTypeFilter] = useState<string | undefined>(undefined);

  // Ollama import modal
  const [ollamaImportOpen, setOllamaImportOpen] = useState(false);

  // KBs that reference a ModelConfig. Loaded once on mount; refreshed
  // after create/edit/import so the delete-disable state is honest.
  const [referencedModelIds, setReferencedModelIds] = useState<Set<number>>(
    () => new Set<number>()
  );

  // Row ids currently mid-toggle on the is_active switch. The Set
  // (rather than a single id) lets the user flip several rows back to
  // back without the first request's spinner masking the others.
  const [togglingActiveIds, setTogglingActiveIds] = useState<Set<number>>(
    () => new Set<number>()
  );

  const fetchKbReferences = async () => {
    try {
      // Pull a wide page so we don't miss references for tenants
      // with many KBs in the future. Backend paginates by default.
      const res = await knowledgeApi.list(1, 100);
      if (res.data?.code === 200 && Array.isArray(res.data.data)) {
        const ids = new Set<number>();
        (res.data.data as KnowledgeBase[]).forEach((kb) => {
          if (kb.embedding_model_config_id != null) {
            ids.add(kb.embedding_model_config_id);
          }
        });
        setReferencedModelIds(ids);
      }
    } catch {
      // Best-effort: leave the previous set in place. The backend
      // will still reject the delete with 422 if the user clicks
      // through anyway.
    }
  };

  const fetchProviders = async () => {
    setProvidersLoading(true);
    setProvidersError(null);
    try {
      const res = await modelsApi.listTypes();
      if (res.data?.code === 200 && Array.isArray(res.data.data)) {
        setProviders(res.data.data);
      } else {
        setProviders(FALLBACK_PROVIDERS);
        setProvidersError("后端返回的 provider 列表无效,已切换为内置列表");
      }
    } catch (err) {
      // Backend endpoint unreachable (e.g. dev server down). Fall back
      // to the hardcoded list so the page is still functional.
      setProviders(FALLBACK_PROVIDERS);
      setProvidersError("无法获取 provider 列表,已切换为内置列表");
    } finally {
      setProvidersLoading(false);
    }
  };

  const fetchModels = async (page = 1, pageSize = 10, type?: string) => {
    setLoading(true);
    try {
      const response = await modelsApi.list(page, pageSize, type);
      if (response.data.code === 200) {
        setModels(response.data.data);
        setPagination({
          current: response.data.page,
          pageSize: response.data.page_size,
          total: response.data.total,
        });
      }
    } catch (error) {
      message.error("获取模型配置列表失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProviders();
    fetchKbReferences();
  }, []);

  useEffect(() => {
    fetchModels(1, pagination.pageSize, typeFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeFilter]);

  const providerOptions = useMemo(
    () =>
      providers.map((p) => ({
        value: p.value,
        label: p.label,
        description: p.description,
        base_url_hint: p.base_url_hint,
      })),
    [providers]
  );

  // Currently selected provider's base_url hint (for the form).
  // The hint auto-fills an empty input on type change but never
  // overwrites a user-typed value.
  const watchedType = Form.useWatch("model_type", form);
  const selectedProvider = useMemo(
    () => providers.find((p) => p.value === watchedType),
    [providers, watchedType]
  );

  const handleCreate = async (values: any) => {
    try {
      const response = await modelsApi.create(values);
      if (response.data.code === 200) {
        message.success("创建成功");
        setModalVisible(false);
        form.resetFields();
        fetchModels(pagination.current, pagination.pageSize, typeFilter);
        fetchKbReferences();
      }
    } catch (error) {
      message.error("创建失败");
    }
  };

  const handleUpdate = async (values: any) => {
    if (!editingId) return;
    try {
      const response = await modelsApi.update(editingId, values);
      if (response.data.code === 200) {
        message.success("更新成功");
        setModalVisible(false);
        setEditingId(null);
        form.resetFields();
        fetchModels(pagination.current, pagination.pageSize, typeFilter);
        fetchKbReferences();
      }
    } catch (error) {
      message.error("更新失败");
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await modelsApi.delete(id);
      message.success("删除成功");
      fetchModels(pagination.current, pagination.pageSize, typeFilter);
      fetchKbReferences();
    } catch (err: any) {
      // Surface the backend's specific 422 message (e.g. "该模型被知识库
      // 引用,无法禁用") so admins know why the delete was refused.
      const detail =
        err?.response?.data?.message ||
        err?.response?.data?.detail ||
        err?.message ||
        "删除失败";
      message.error(detail);
    }
  };

  const openEditModal = (record: ModelConfig) => {
    setEditingId(record.id);
    form.setFieldsValue(record);
    setModalVisible(true);
  };

  // Toggle is_active straight from the list — the edit modal doesn't
  // expose this field, so a switch in the table is the only path. The
  // backend's update handler invalidates the embedding cache whenever
  // is_active changes, so we don't need to do that here.
  const handleToggleActive = async (id: number, next: boolean) => {
    const previous = models.find((m) => m.id === id)?.is_active;
    // Optimistic update: flip the row immediately so the Switch
    // reflects the new state without waiting for the round-trip.
    setModels((prev) =>
      prev.map((m) => (m.id === id ? { ...m, is_active: next } : m))
    );
    setTogglingActiveIds((prev) => {
      const n = new Set(prev);
      n.add(id);
      return n;
    });
    try {
      const response = await modelsApi.update(id, { is_active: next });
      if (response.data?.code !== 200) {
        // Backend rejected (validation, race, etc.) — roll back and
        // surface its message so the admin knows what happened.
        setModels((prev) =>
          prev.map((m) =>
            m.id === id ? { ...m, is_active: previous ?? false } : m
          )
        );
        message.error(response.data?.message || "状态更新失败");
      }
    } catch (err: any) {
      setModels((prev) =>
        prev.map((m) =>
          m.id === id ? { ...m, is_active: previous ?? false } : m
        )
      );
      const detail =
        err?.response?.data?.message ||
        err?.response?.data?.detail ||
        err?.message ||
        "状态更新失败";
      message.error(detail);
    } finally {
      setTogglingActiveIds((prev) => {
        const n = new Set(prev);
        n.delete(id);
        return n;
      });
    }
  };

  const columns: ColumnsType<ModelConfig> = [
    {
      title: "ID",
      dataIndex: "id",
      key: "id",
      width: 60,
    },
    {
      title: "名称",
      dataIndex: "name",
      key: "name",
    },
    {
      title: "类型",
      dataIndex: "model_type",
      key: "model_type",
      render: (type) => {
        const option = providers.find((o) => o.value === type);
        return <Tag color="blue">{option?.label || type}</Tag>;
      },
    },
    {
      title: "模型",
      dataIndex: "model_name",
      key: "model_name",
    },
    {
      title: "用途",
      key: "purpose",
      width: 180,
      render: (_, record) => {
        // Multi-purpose: render one tag per enabled flag. Order is fixed
        // (Chat → Embed → Image) so the column stays scannable when rows
        // have a mix of flags. None set: a grey "未指定" tag so the column
        // never renders empty.
        const isChat = Boolean(record.is_chat);
        const isEmbed = Boolean(record.is_embedding);
        const isImage = Boolean(record.is_image_generation);
        const tags: JSX.Element[] = [];
        if (isChat) tags.push(<Tag key="chat" color="blue">Chat</Tag>);
        if (isEmbed) tags.push(<Tag key="embed" color="purple">Embed</Tag>);
        if (isImage) tags.push(<Tag key="image" color="green">Image</Tag>);
        if (tags.length === 0) return <Tag>未指定</Tag>;
        return <Space size={4} wrap>{tags}</Space>;
      },
    },
    {
      title: "Base URL",
      dataIndex: "base_url",
      key: "base_url",
      ellipsis: true,
    },
    {
      title: "默认",
      dataIndex: "is_default",
      key: "is_default",
      width: 80,
      render: (isDefault) =>
        isDefault ? (
          <Tag icon={<CheckCircleOutlined />} color="success">
            默认
          </Tag>
        ) : (
          "-"
        ),
    },
    {
      title: "状态",
      key: "is_active",
      width: 100,
      render: (_, record) => (
        <Tooltip
          title={
            record.is_active
              ? "点击禁用此模型(后端会清掉对应的 embedding 缓存)"
              : "点击启用此模型"
          }
        >
          <Switch
            size="small"
            checked={record.is_active}
            loading={togglingActiveIds.has(record.id)}
            onChange={(checked) => handleToggleActive(record.id, checked)}
            checkedChildren="启用"
            unCheckedChildren="禁用"
          />
        </Tooltip>
      ),
    },
    {
      title: "操作",
      key: "action",
      width: 150,
      render: (_, record) => {
        const isReferenced = referencedModelIds.has(record.id);
        const deleteBtn = (
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            disabled={isReferenced}
          >
            删除
          </Button>
        );
        return (
          <Space>
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => openEditModal(record)}
            >
              编辑
            </Button>
            {isReferenced ? (
              <Tooltip title="该模型被知识库引用,无法删除">
                {deleteBtn}
              </Tooltip>
            ) : (
              <Popconfirm
                title="确认删除此模型配置?"
                onConfirm={() => handleDelete(record.id)}
              >
                {deleteBtn}
              </Popconfirm>
            )}
          </Space>
        );
      },
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Card
        title="AI 模型配置"
        extra={
          <Space>
            <Button
              icon={<ReloadOutlined />}
              onClick={fetchProviders}
              loading={providersLoading}
              title="刷新 provider 列表"
            >
              刷新
            </Button>
            <Button
              icon={<LinkOutlined />}
              onClick={() => setOllamaImportOpen(true)}
              title="从本地 Ollama 拉取已下载模型并批量入库"
            >
              从 Ollama 导入
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => {
                setEditingId(null);
                form.resetFields();
                setModalVisible(true);
              }}
            >
              添加模型
            </Button>
          </Space>
        }
      >
        {providersError && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message={providersError}
          />
        )}

        <div style={{ marginBottom: 16 }}>
          <Spin spinning={providersLoading}>
            <Row gutter={[12, 12]}>
              {providers.map((type) => (
                <Col xs={24} sm={12} md={8} lg={6} key={type.value}>
                  <Card size="small" title={type.label}>
                    <p style={{ color: "#666", fontSize: 12, marginBottom: 6, minHeight: 32 }}>
                      {type.description}
                    </p>
                    {type.base_url_hint && (
                      <Tooltip title="点击复制">
                        <code
                          style={{
                            display: "inline-block",
                            fontSize: 11,
                            color: "#1677ff",
                            background: "#f0f5ff",
                            padding: "2px 6px",
                            borderRadius: 3,
                            cursor: "pointer",
                            maxWidth: "100%",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                          onClick={() => {
                            navigator.clipboard?.writeText(type.base_url_hint || "");
                            message.success("已复制");
                          }}
                        >
                          <LinkOutlined style={{ marginRight: 4 }} />
                          {type.base_url_hint}
                        </code>
                      </Tooltip>
                    )}
                  </Card>
                </Col>
              ))}
            </Row>
          </Spin>
        </div>

        <Space style={{ marginBottom: 12 }}>
          <span style={{ color: "#666" }}>按类型筛选:</span>
          <Select
            allowClear
            placeholder="全部类型"
            style={{ minWidth: 200 }}
            value={typeFilter}
            onChange={setTypeFilter}
            options={providerOptions.map((p) => ({ value: p.value, label: p.label }))}
          />
        </Space>

        <Table
          columns={columns}
          dataSource={models}
          rowKey="id"
          loading={loading}
          locale={{ emptyText: <Empty description="暂无模型配置" /> }}
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: pagination.total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (page, pageSize) => fetchModels(page, pageSize, typeFilter),
          }}
        />
      </Card>

      <Modal
        title={editingId ? "编辑模型配置" : "添加模型配置"}
        open={modalVisible}
        onCancel={() => {
          setModalVisible(false);
          setEditingId(null);
          form.resetFields();
        }}
        footer={null}
        width={600}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={editingId ? handleUpdate : handleCreate}
          initialValues={{
            temperature: 0.7,
            max_tokens: 4096,
            timeout: 120,
            is_default: false,
            // Default the purpose flags so a freshly created row
            // is always useful for at least one of the consumers.
            // The backend schema defaults is_chat=True / is_embedding=False /
            // is_image_generation=False; matching that here avoids a
            // Pydantic validation ping on save.
            is_chat: true,
            is_embedding: false,
            is_image_generation: false,
          }}
        >
          <Form.Item
            name="name"
            label="配置名称"
            rules={[{ required: true, message: "请输入配置名称" }]}
          >
            <Input placeholder="如: 我的 Ollama / 团队 DeepSeek" />
          </Form.Item>

          <Form.Item
            name="model_type"
            label="模型类型"
            rules={[{ required: true, message: "请选择模型类型" }]}
          >
            <Select
              placeholder="选择模型类型"
              options={providerOptions}
              optionRender={(option) => (
                <Space direction="vertical" size={0} style={{ lineHeight: 1.2 }}>
                  <span>{option.label}</span>
                  <span style={{ fontSize: 11, color: "#999" }}>
                    {option.data?.description}
                  </span>
                </Space>
              )}
            />
          </Form.Item>

          <Form.Item
            name="model_name"
            label="模型名称"
            rules={[{ required: true, message: "请输入模型名称" }]}
            extra={
              selectedProvider?.base_url_hint
                ? `该 provider 的 base_url 为 ${selectedProvider.base_url_hint}`
                : undefined
            }
          >
            <Input placeholder="如: qwen2.5:7b, gpt-4o, claude-3-5-sonnet, deepseek-chat" />
          </Form.Item>

          <Form.Item
            name="base_url"
            label="Base URL"
            extra={
              selectedProvider?.base_url_hint
                ? `典型值: ${selectedProvider.base_url_hint}`
                : "Ollama 默认 http://localhost:11434"
            }
          >
            <Input
              placeholder={selectedProvider?.base_url_hint || "http://localhost:11434"}
            />
          </Form.Item>

          <Form.Item name="api_key" label="API Key" extra="Ollama 不需要">
            <Input.Password placeholder="API 密钥 (OpenAI / DeepSeek / Qwen 等需要)" />
          </Form.Item>

          <Form.Item name="api_version" label="API Version" extra="仅 Azure OpenAI 等部分 provider 需要">
            <Input placeholder="如: 2024-01-01" />
          </Form.Item>

          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="temperature" label="Temperature">
                <InputNumber min={0} max={2} step={0.1} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="max_tokens" label="最大Token">
                <InputNumber min={100} max={128000} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="timeout" label="超时(秒)">
                <InputNumber min={10} max={300} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item name="is_default" label="设为默认模型" valuePropName="checked">
            <Switch />
          </Form.Item>

          <Divider style={{ margin: "8px 0 16px" }}>用途</Divider>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name="is_chat"
                label="用作对话模型"
                valuePropName="checked"
                extra="开启后可在 Agent / 节点里作为 chat 模型引用"
              >
                <Switch checkedChildren="Chat" unCheckedChildren="Chat" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="is_embedding"
                label="用作 embedding 模型"
                valuePropName="checked"
                extra="开启后可作为知识库的 embedding 模型;仅 ollama / openai 支持"
              >
                <Switch checkedChildren="Embed" unCheckedChildren="Embed" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="is_image_generation"
                label="用作图片生成模型"
                valuePropName="checked"
                extra="开启后可在「图片生成」页面选择该模型"
              >
                <Switch checkedChildren="Image" unCheckedChildren="Image" />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item name="description" label="描述">
            <TextArea placeholder="模型配置描述..." rows={2} />
          </Form.Item>

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                {editingId ? "更新" : "创建"}
              </Button>
              <Button
                onClick={() => {
                  setModalVisible(false);
                  setEditingId(null);
                  form.resetFields();
                }}
              >
                取消
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      <OllamaImportModal
        open={ollamaImportOpen}
        onClose={() => setOllamaImportOpen(false)}
        onSuccess={() => {
          // Refresh both lists so a newly-imported row shows up
          // and the reference set is up to date.
          fetchModels(pagination.current, pagination.pageSize, typeFilter);
          fetchKbReferences();
        }}
      />
    </div>
  );
}
