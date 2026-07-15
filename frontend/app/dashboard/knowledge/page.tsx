"use client";

import { useState, useEffect } from "react";
import {
  Table,
  Button,
  Space,
  Modal,
  Form,
  Input,
  InputNumber,
  Upload,
  message,
  Popconfirm,
  Card,
  List,
  Typography,
  Tag,
  Divider,
  Select,
  Collapse,
  Slider,
  Switch,
  Tabs,
} from "antd";
import {
  PlusOutlined,
  UploadOutlined,
  SearchOutlined,
  FileTextOutlined,
  DeleteOutlined,
  SettingOutlined,
  EditOutlined,
  RedoOutlined,
  BarsOutlined,
  AppstoreOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { knowledgeApi, ParserType, DocumentResponse, DocumentChunk } from "@/services/knowledge";
import type { KnowledgeBase } from "@/types/api";
import EmbeddingModelSelect from "@/components/EmbeddingModelSelect";
import FAQTab from "@/components/knowledge/FAQTab";
import { ModelConfig } from "@/services/models";
import { useNotificationsStore } from "@/store/notifications";

const { TextArea } = Input;
const { Text } = Typography;
const { Panel } = Collapse;

interface SearchResult {
  id: string;
  text: string;
  distance: number;
  metadata: {
    chunk_id: number;
    document_id: number;
    tenant_id: number;
    kb_id: number;
  };
}

// Shared "delete this document" action — used by the inline list and
// the docListModal. Keeping the confirm copy and the danger styling in
// one place so the two call sites can never silently diverge.
function DeleteDocumentAction({
  loading,
  onConfirm,
}: {
  loading: boolean;
  onConfirm: () => void;
}) {
  return (
    <Popconfirm
      key="delete"
      title="确定要删除此文档吗？分块和向量索引也会一并清除。"
      okText="删除"
      okButtonProps={{ danger: true }}
      cancelText="取消"
      onConfirm={onConfirm}
    >
      <Button
        size="small"
        type="link"
        danger
        icon={<DeleteOutlined />}
        loading={loading}
      >
        删除
      </Button>
    </Popconfirm>
  );
}

export default function KnowledgePage() {
  const [data, setData] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [form] = Form.useForm();
  // Server-side pagination for the KB list. The /knowledge/ endpoint returns
  // a PaginatedResponse; without explicit state the AntD Table can only show
  // the first 10 rows the server returned.
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [total, setTotal] = useState(0);

  // Search state
  const [selectedKB, setSelectedKB] = useState<KnowledgeBase | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  // Documents state
  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState<SearchResult | null>(null);

  // Upload state
  const [selectedDocType, setSelectedDocType] = useState<string>("");

  // Search options state
  const [searchOptions, setSearchOptions] = useState({
    k: 5,
    alpha: 0.5,
    rerank: true,
    rerankTopN: 10,
    fieldWeights: "",
  });

  // Search weights state
  const [searchWeights, setSearchWeights] = useState({
    title: 10.0,
    important_kw: 30.0,
    question_kw: 20.0,
    text: 2.0,
  });

  // Embedding models loaded by the create modal's <EmbeddingModelSelect/>.
  // The child pushes the list up via `onLoaded`; we use it to auto-pick
  // a default the moment the create modal opens (no empty-then-filled
  // flash, no manual click). Cached at the page level so re-opening the
  // modal after a cancel/submit is instant.
  const [loadedEmbeddingModels, setLoadedEmbeddingModels] = useState<
    ModelConfig[]
  >([]);

  // Edit modal state
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [editForm] = Form.useForm();
  const [editingKB, setEditingKB] = useState<KnowledgeBase | null>(null);
  const [editSearchWeights, setEditSearchWeights] = useState({
    title: 10.0,
    important_kw: 30.0,
    question_kw: 20.0,
    text: 2.0,
  });

  // Document list modal state
  const [docListModalVisible, setDocListModalVisible] = useState(false);
  const [docListKB, setDocListKB] = useState<KnowledgeBase | null>(null);
  const [docList, setDocList] = useState<DocumentResponse[]>([]);
  const [docListLoading, setDocListLoading] = useState(false);

  // Per-doc loading state for the retry button (one spinner at a time).
  const [retryingDocId, setRetryingDocId] = useState<number | null>(null);

  // Per-doc loading state for the delete button. Spinner is shown on
  // the row that's currently being deleted so concurrent deletes are
  // impossible.
  const [deletingDocId, setDeletingDocId] = useState<number | null>(null);

  // M28: 删 KB 被 agent/document 引用 → 后端 422 + blockers 列表。
  // toast 3 秒就消失,根本看不清要解绑哪个 agent,改成 Modal 持久展示。
  const [blockerModal, setBlockerModal] = useState<{
    visible: boolean;
    message: string;
    agents: { id: number; name: string }[];
    documents: { id: number; filename: string }[];
    truncated: boolean;
  }>({
    visible: false,
    message: "",
    agents: [],
    documents: [],
    truncated: false,
  });

  // View-chunks modal state
  const [chunksModalOpen, setChunksModalOpen] = useState(false);
  const [chunksDoc, setChunksDoc] = useState<DocumentResponse | null>(null);
  const [chunks, setChunks] = useState<DocumentChunk[]>([]);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [chunksPage, setChunksPage] = useState(1);
  const [chunksPageSize, setChunksPageSize] = useState(20);

  // Re-chunk modal state
  const [rechunkModalOpen, setRechunkModalOpen] = useState(false);
  const [rechunkDoc, setRechunkDoc] = useState<DocumentResponse | null>(null);
  const [rechunkSubmitting, setRechunkSubmitting] = useState(false);
  const [rechunkForm] = Form.useForm();

  // Fetch parser types
  const { data: parserTypesData } = useQuery({
    queryKey: ["parserTypes"],
    queryFn: () => knowledgeApi.getParserTypes(),
  });
  const parserTypes = parserTypesData?.data?.data?.parser_types || [];

  const queryClient = useQueryClient();

  const searchParams = useSearchParams();

  useEffect(() => {
    // Subscribe to incoming notifications; refetch the current KB's doc
    // list when a doc-related notification for that KB arrives.
    const unsub = useNotificationsStore.subscribe((state, prev) => {
      if (state.items === prev.items) return;
      const newest = state.items[0];
      if (!newest) return;
      if (
        newest.resource_type === "document" &&
        selectedKB !== null &&
        newest.metadata?.kb_id === selectedKB.id &&
        // Only react to length growth (WS push, refetchUnread backfill, loadMore).
        // Pure state swaps like markRead/markAllRead/reset don't change length,
        // so they don't trigger a refetch.
        prev.items.length < state.items.length
      ) {
        fetchDocuments(selectedKB.id);
      }
    });
    return () => { unsub(); };
  }, [selectedKB?.id]);

  // Highlight a specific doc when the URL has ?doc=<id> — used by the
  // notification "Open" action to deep-link into the KB page.
  const docParam = searchParams.get("doc");
  useEffect(() => {
    if (!docParam) return;
    // Wait one tick for the doc list to be rendered
    const t = setTimeout(() => {
      const el = document.querySelector(`[data-doc-id="${docParam}"]`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        (el as HTMLElement).style.transition = "background 0.5s";
        (el as HTMLElement).style.background = "#fff7e6";
        setTimeout(() => { (el as HTMLElement).style.background = ""; }, 1500);
      }
    }, 300);
    return () => clearTimeout(t);
  }, [docParam, documents.length, docList.length]);

  // Upload mutation - background safe, survives page navigation
  const uploadMutation = useMutation({
    mutationFn: ({ kbId, file, docType }: { kbId: number; file: File; docType?: string }) =>
      knowledgeApi.upload(kbId, file, docType),
    onMutate: () => {
      message.loading("上传中...", 0);
    },
    onSuccess: (response, variables) => {
      message.destroy();
      if (response.data.code === 200) {
        message.success("上传成功");
      } else {
        message.error(response.data.message || "上传失败");
      }
      // Refresh the KB list so the document-count badge on the row
      // updates immediately after upload (otherwise it stays stale).
      fetchData();
      // Refresh the right-side document list if a KB is selected
      if (selectedKB) {
        queryClient.invalidateQueries({ queryKey: ["documents", selectedKB.id] });
        fetchDocuments(selectedKB.id);
      }
    },
    onError: (error: any) => {
      message.destroy();
      if (error.response?.status === 413) {
        message.error("文件太大");
      } else {
        message.error("上传失败");
      }
    },
  });

  const fetchData = async () => {
    setLoading(true);
    try {
      const response = await knowledgeApi.list(page, pageSize);
      if (response.data.code === 200) {
        setData(response.data.data || []);
        setTotal(response.data.total || 0);
      }
    } catch (error) {
      message.error("获取知识库列表失败");
    } finally {
      setLoading(false);
    }
  };

  const fetchDocuments = async (kbId: number) => {
    setLoadingDocs(true);
    try {
      const response = await knowledgeApi.getDocuments(kbId);
      if (response.data.code === 200) {
        setDocuments(response.data.data || []);
      }
    } catch (error) {
      message.error("加载文档列表失败");
    } finally {
      setLoadingDocs(false);
    }
  };

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize]);

  // Auto-default the create-KB form's `embedding_model_config_id` to
  // the user's `is_default` embedding model (or the first available).
  // Runs whenever the create modal opens AND the embedding list is
  // already in hand (cached after first load by React Query). The
  // empty-then-filled guard is so we never clobber a value the user
  // just picked manually.
  useEffect(() => {
    if (!modalVisible) return;
    if (loadedEmbeddingModels.length === 0) return;
    const current = form.getFieldValue("embedding_model_config_id");
    if (current) return;
    const def =
      loadedEmbeddingModels.find((m) => m.is_default) ||
      loadedEmbeddingModels[0];
    form.setFieldValue("embedding_model_config_id", def.id);
  }, [modalVisible, loadedEmbeddingModels, form]);

  const handleSelectKB = (kb: KnowledgeBase | null) => {
    setSelectedKB(kb);
    setSearchResults([]);
    setSearchQuery("");
    if (kb) {
      fetchDocuments(kb.id);
    } else {
      setDocuments([]);
    }
  };

  const handleCreate = async (values: any) => {
    try {
      // Spread the form values (name, description,
      // embedding_model_config_id, default_parser, chunk_*); AntD
      // gives us exactly the form's named fields.
      const payload = {
        ...values,
        search_weights: searchWeights,
      };
      const response = await knowledgeApi.create(payload);
      if (response.data.code === 200) {
        message.success("创建成功");
        setModalVisible(false);
        form.resetFields();
        fetchData();
      }
    } catch (error) {
      message.error("创建失败");
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await knowledgeApi.delete(id);
      message.success("删除成功");
      if (selectedKB?.id === id) {
        handleSelectKB(null);
      }
      fetchData();
    } catch (error: any) {
      // M28: 422 = 引用计数拦截 → 用 Modal 展示具体是哪个 agent / 哪份文档在卡,
      // 不再让用户对着一个 "agent_count: 1" 冷数字猜去哪儿解绑。
      const status = error?.response?.status;
      const detail = error?.response?.data?.detail;
      if (status === 422 && detail && typeof detail === "object") {
        setBlockerModal({
          visible: true,
          message:
            typeof detail.message === "string"
              ? detail.message
              : "该知识库仍被其他资源引用,无法删除。",
          agents: Array.isArray(detail.blocking_agents) ? detail.blocking_agents : [],
          documents: Array.isArray(detail.blocking_documents)
            ? detail.blocking_documents
            : [],
          truncated: detail.truncated === true,
        });
        return;
      }
      // 兜底:detail 是 string (如 400/404) → message.error 显示原文
      const fallback = typeof detail === "string" ? detail : "删除失败";
      message.error(fallback);
    }
  };

  const handleEdit = (kb: KnowledgeBase) => {
    setEditingKB(kb);
    // Initialize form with existing values
    editForm.setFieldsValue({
      name: kb.name,
      description: kb.description,
      // Prefer the new FK; fall back to the legacy string for KBs
      // that haven't yet been back-filled by the migration script.
      embedding_model_config_id:
        kb.embedding_model_config_id ?? undefined,
      default_parser: kb.default_parser || "general",
      chunk_size: kb.chunk_size || 500,
      chunk_overlap: kb.chunk_overlap || 50,
    });
    // Initialize search weights
    if (kb.search_weights) {
      setEditSearchWeights({
        title: kb.search_weights.title || 10.0,
        important_kw: kb.search_weights.important_kw || 30.0,
        question_kw: kb.search_weights.question_kw || 20.0,
        text: kb.search_weights.text || 2.0,
      });
    }
    setEditModalVisible(true);
  };

  const handleUpdate = async (values: any) => {
    if (!editingKB) return;
    try {
      const payload = {
        ...values,
        search_weights: editSearchWeights,
      };
      const response = await knowledgeApi.update(editingKB.id, payload);
      if (response.data.code === 200) {
        message.success("更新成功");
        setEditModalVisible(false);
        editForm.resetFields();
        fetchData();
        // Update selectedKB if it's the one being edited
        if (selectedKB?.id === editingKB.id) {
          setSelectedKB({ ...selectedKB, ...response.data.data });
        }
      }
    } catch (error) {
      message.error("更新失败");
    }
  };

  const handleUpload = (kbId: number, file: File) => {
    uploadMutation.mutate({ kbId, file, docType: selectedDocType });
    return false; // prevent default upload behavior
  };

  const handleViewDocs = async (kb: KnowledgeBase) => {
    setDocListKB(kb);
    setDocListModalVisible(true);
    setDocListLoading(true);
    try {
      const response = await knowledgeApi.getDocuments(kb.id);
      if (response.data.code === 200) {
        setDocList(response.data.data || []);
      }
    } catch (error) {
      message.error("加载文档列表失败");
      setDocList([]);
    } finally {
      setDocListLoading(false);
    }
  };

  const handleRetry = async (doc: DocumentResponse) => {
    setRetryingDocId(doc.id);
    try {
      const response = await knowledgeApi.retry(doc.id);
      if (response.data.code === 200) {
        message.success("已重新加入处理队列");
        // Refresh whichever list currently shows this doc.
        if (docListModalVisible && docListKB) {
          await handleViewDocs(docListKB);
        }
        if (selectedKB) {
          await fetchDocuments(selectedKB.id);
        }
      } else {
        message.error(response.data.message || "重试失败");
      }
    } catch (error: any) {
      const detail = error?.response?.data?.detail || error?.message || "重试失败";
      message.error(detail);
    } finally {
      setRetryingDocId(null);
    }
  };

  const handleDeleteDocument = async (doc: DocumentResponse) => {
    setDeletingDocId(doc.id);
    try {
      const response = await knowledgeApi.deleteDocument(doc.id);
      if (response.data.code === 200) {
        const payload = response.data.data as
          | { deleted_chunks: number; vector_cleanup_failed: boolean }
          | undefined;
        const chunksNote = payload?.deleted_chunks
          ? `,清除 ${payload.deleted_chunks} 个分块`
          : "";
        const vectorNote = payload?.vector_cleanup_failed
          ? "（向量清理未完全成功,可重试或忽略）"
          : "";
        message.success(`文档已删除${chunksNote}${vectorNote}`);
        // Refresh whichever lists show this doc. The modal and the
        // inline list share a single document set when they refer to
        // the same KB — refreshing the modal also keeps the inline
        // list in sync via the next fetchData().
        if (docListModalVisible && docListKB) {
          await handleViewDocs(docListKB);
          if (selectedKB && selectedKB.id !== docListKB.id) {
            await fetchDocuments(selectedKB.id);
          }
        } else if (selectedKB) {
          await fetchDocuments(selectedKB.id);
        }
        // KB row's `document_count` is derived in the service layer;
        // the manual fetchData() refetch below updates the badge.
        await fetchData();
      } else {
        message.error(response.data.message || "删除失败");
      }
    } catch (error: any) {
      const detail =
        error?.response?.data?.detail || error?.message || "删除失败";
      message.error(typeof detail === "string" ? detail : JSON.stringify(detail));
    } finally {
      setDeletingDocId(null);
    }
  };

  const fetchChunks = async (docId: number, page: number, pageSize: number) => {
    setChunksLoading(true);
    try {
      const response = await knowledgeApi.listChunks(docId, page, pageSize);
      if (response.data.code === 200) {
        setChunks(response.data.data || []);
      }
    } catch (error: any) {
      const detail = error?.response?.data?.detail || error?.message || "加载分块失败";
      message.error(detail);
      setChunks([]);
    } finally {
      setChunksLoading(false);
    }
  };

  const handleViewChunks = (doc: DocumentResponse) => {
    setChunksDoc(doc);
    setChunksPage(1);
    setChunksModalOpen(true);
    fetchChunks(doc.id, 1, chunksPageSize);
  };

  const handleRechunk = (doc: DocumentResponse) => {
    setRechunkDoc(doc);
    // Pre-fill form with the doc's currently-stored doc_type and the
    // parent KB's chunking settings as a sensible default.
    const kb = doc.knowledge_base_id
      ? data.find((k) => k.id === doc.knowledge_base_id) || selectedKB
      : null;
    const existingDocType = doc.doc_metadata?.doc_type;
    rechunkForm.setFieldsValue({
      chunking_strategy: "fixed",
      chunk_size: (kb as any)?.chunk_size ?? 500,
      chunk_overlap: (kb as any)?.chunk_overlap ?? 50,
      doc_type: existingDocType,
    });
    setRechunkModalOpen(true);
  };

  const handleRechunkSubmit = async (values: {
    chunking_strategy: string;
    chunk_size: number;
    chunk_overlap: number;
    doc_type?: string;
  }) => {
    if (!rechunkDoc) return;
    setRechunkSubmitting(true);
    try {
      const response = await knowledgeApi.rechunk(rechunkDoc.id, values);
      if (response.data.code === 200) {
        message.success("已提交重新分块任务");
        setRechunkModalOpen(false);
        rechunkForm.resetFields();
        if (docListModalVisible && docListKB) {
          await handleViewDocs(docListKB);
        }
        if (selectedKB) {
          await fetchDocuments(selectedKB.id);
        }
      } else {
        message.error(response.data.message || "重新分块失败");
      }
    } catch (error: any) {
      const detail = error?.response?.data?.detail || error?.message || "重新分块失败";
      message.error(detail);
    } finally {
      setRechunkSubmitting(false);
    }
  };

  const handleSearch = async () => {
    if (!selectedKB || !searchQuery.trim()) {
      message.warning("请选择知识库并输入搜索内容");
      return;
    }
    setSearching(true);
    try {
      const options = {
        k: searchOptions.k,
        alpha: searchOptions.alpha,
        rerank: searchOptions.rerank,
        rerank_top_n: searchOptions.rerankTopN,
        field_weights: searchOptions.fieldWeights || undefined,
      };
      const response = await knowledgeApi.search(selectedKB.id, searchQuery, options);
      if (response.data.code === 200) {
        setSearchResults(response.data.data || []);
        if ((response.data.data || []).length === 0) {
          message.info("未找到相关结果");
        }
      }
    } catch (error) {
      message.error("搜索失败");
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  };

  const showDetail = (result: SearchResult) => {
    setSelectedDoc(result);
    setDetailModalVisible(true);
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  };

  const columns: ColumnsType<KnowledgeBase> = [
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
      title: "描述",
      dataIndex: "description",
      key: "description",
      ellipsis: true,
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 80,
      render: (status: string) => (
        <Tag color={status === "active" ? "green" : "default"}>
          {status === "active" ? "启用" : "停用"}
        </Tag>
      ),
    },
    {
      title: "Embedding",
      dataIndex: "embedding_model",
      key: "embedding_model",
      width: 120,
      ellipsis: true,
    },
    {
      title: "解析器",
      dataIndex: "default_parser",
      key: "default_parser",
      width: 80,
      render: (parser: string) => {
        const parserMap: Record<string, string> = {
          general: "通用",
          paper: "论文",
          qa: "问答",
          table: "表格",
          manual: "手册",
          laws: "法律",
        };
        return parserMap[parser] || parser || "通用";
      },
    },
    {
      title: "分块",
      key: "chunk",
      width: 100,
      render: (_, record) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {record.chunk_size || 500}/{record.chunk_overlap || 50}
        </Text>
      ),
    },
    {
      title: "文档",
      key: "docs",
      width: 100,
      render: (_, record) => (
        <Button
          size="small"
          type="link"
          onClick={() => handleViewDocs(record)}
        >
          {record.document_count ?? 0} 个文档
        </Button>
      ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 180,
    },
    {
      title: "操作",
      key: "action",
      width: 280,
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            type={selectedKB?.id === record.id ? "primary" : "default"}
            icon={<SearchOutlined />}
            onClick={() => handleSelectKB(selectedKB?.id === record.id ? null : record)}
          >
            {selectedKB?.id === record.id ? "取消选择" : "查看"}
          </Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
            编辑
          </Button>
          <Upload
            showUploadList={false}
            beforeUpload={(file) => handleUpload(record.id, file)}
          >
            <Button
              size="small"
              icon={<UploadOutlined />}
              loading={uploadMutation.isPending && uploadMutation.variables?.kbId === record.id}
            >
              上传
            </Button>
          </Upload>
          <Popconfirm
            title="确认删除?"
            onConfirm={() => handleDelete(record.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      {/* Knowledge Base List */}
      <Card title="知识库列表" style={{ marginBottom: 16 }}>
        <div style={{ marginBottom: 16 }}>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setModalVisible(true)}
          >
            创建知识库
          </Button>
        </div>
        <Table
          columns={columns}
          dataSource={data}
          rowKey="id"
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => {
              setPage(p);
              setPageSize(ps);
            },
          }}
          size="small"
        />
      </Card>

      {/* Selected KB Detail and Documents */}
      {selectedKB && (
        <>
          <Card title={`知识库详情: ${selectedKB.name}`} style={{ marginBottom: 16 }}>
            <p><Text strong>ID:</Text> {selectedKB.id}</p>
            <p><Text strong>描述:</Text> {selectedKB.description || "无"}</p>
            <p><Text strong>Embedding模型:</Text> {selectedKB.embedding_model}</p>
            <p><Text strong>默认解析器:</Text> {
              (selectedKB as any).default_parser ?
                (parserTypes.find((t: any) => t.type === (selectedKB as any).default_parser)?.label || (selectedKB as any).default_parser)
                : "通用文档"
            }</p>
            <p><Text strong>分块配置:</Text> 块大小 {(selectedKB as any).chunk_size || 500} / 重叠 {(selectedKB as any).chunk_overlap || 50}</p>
            <p><Text strong>状态:</Text> <Tag color={selectedKB.status === "active" ? "green" : "default"}>{selectedKB.status}</Tag></p>
            <p><Text strong>创建时间:</Text> {selectedKB.created_at}</p>
          </Card>

          {/* Documents + Q&A Section — Tabs (M31) */}
          <Card style={{ marginBottom: 16 }} styles={{ body: { paddingTop: 12 } }}>
            <Tabs
              data-testid="kb-content-tabs"
              items={[
                {
                  key: "documents",
                  label: "已上传文档",
                  children: (
                    <div>
                      <Space style={{ marginBottom: 12 }}>
                        <Select
                          placeholder="文档类型"
                          allowClear
                          style={{ width: 120 }}
                          value={selectedDocType || undefined}
                          onChange={(value) => setSelectedDocType(value || "")}
                          options={parserTypes.map((t: ParserType) => ({
                            label: t.label,
                            value: t.type,
                          }))}
                        />
                        <Upload
                          showUploadList={false}
                          beforeUpload={(file) => handleUpload(selectedKB.id, file)}
                        >
                          <Button
                            size="small"
                            icon={<UploadOutlined />}
                            loading={uploadMutation.isPending && uploadMutation.variables?.kbId === selectedKB.id}
                          >
                            上传文档
                          </Button>
                        </Upload>
                      </Space>
                      {loadingDocs ? (
                        <Text type="secondary">加载中...</Text>
                      ) : documents.length === 0 ? (
                        <Text type="secondary">暂无文档，请上传</Text>
                      ) : (
                        <List
                          size="small"
                          dataSource={documents}
                          renderItem={(doc) => {
                            const docType = doc.doc_metadata?.doc_type;
                            const retriable = ["pending", "queued", "processing"].includes(doc.status);
                            return (
                            <List.Item
                              data-doc-id={String(doc.id)}
                              actions={[
                                doc.status === "completed" && (
                                  <Button
                                    key="view-chunks"
                                    size="small"
                                    type="link"
                                    icon={<BarsOutlined />}
                                    onClick={() => handleViewChunks(doc)}
                                  >
                                    查看分块
                                  </Button>
                                ),
                                <Button
                                  key="rechunk"
                                  size="small"
                                  type="link"
                                  icon={<AppstoreOutlined />}
                                  onClick={() => handleRechunk(doc)}
                                >
                                  重新分块
                                </Button>,
                                retriable && (
                                  <Popconfirm
                                    key="retry"
                                    title="确定要重新处理此文档吗？之前的分块会被清除。"
                                    onConfirm={() => handleRetry(doc)}
                                  >
                                    <Button
                                      size="small"
                                      type="link"
                                      icon={<RedoOutlined />}
                                      loading={retryingDocId === doc.id}
                                    >
                                      重试
                                    </Button>
                                  </Popconfirm>
                                ),
                                <DeleteDocumentAction
                                  loading={deletingDocId === doc.id}
                                  onConfirm={() => handleDeleteDocument(doc)}
                                />,
                                docType && (
                                  <Tag key="type" color="blue">
                                    {parserTypes.find((t: ParserType) => t.type === docType)?.label || docType}
                                  </Tag>
                                ),
                                <Tag key="status" color={doc.status === "completed" ? "green" : doc.status === "failed" ? "red" : doc.status === "queued" ? "purple" : "orange"}>
                                  {doc.status === "completed" ? "已完成" : doc.status === "failed" ? "失败" : doc.status === "queued" ? "排队中" : "处理中"}
                                </Tag>,
                                doc.chunk_count && <Text key="chunks" type="secondary">分块: {doc.chunk_count}</Text>,
                                <Text key="size" type="secondary">{formatFileSize(doc.file_size)}</Text>,
                              ]}
                            >
                              <List.Item.Meta
                                avatar={<FileTextOutlined />}
                                title={<Text>{doc.filename}</Text>}
                                description={`上传时间: ${doc.created_at}`}
                              />
                            </List.Item>
                            );
                          }}
                        />
                      )}
                    </div>
                  ),
                },
                {
                  key: "faq",
                  label: "Q&A 问答",
                  children: <FAQTab kbId={selectedKB.id} />,
                },
              ]}
            />
          </Card>

          {/* Search Section */}
          <Card title="文档搜索">
            <Space direction="vertical" style={{ width: "100%" }} size="middle">
              <TextArea
                placeholder="输入搜索内容..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onPressEnter={(e) => {
                  e.preventDefault();
                  handleSearch();
                }}
                rows={3}
              />

              <Collapse ghost>
                <Panel header={<Space><SettingOutlined />高级选项</Space>} key="advanced">
                  <Space direction="vertical" style={{ width: "100%" }} size="small">
                    <div>
                      <Text>返回数量 (k): {searchOptions.k}</Text>
                      <Slider
                        min={1}
                        max={50}
                        value={searchOptions.k}
                        onChange={(value) => setSearchOptions({ ...searchOptions, k: value })}
                      />
                    </div>
                    <div>
                      <Text>向量权重 (alpha): {searchOptions.alpha.toFixed(2)}</Text>
                      <Slider
                        min={0}
                        max={1}
                        step={0.1}
                        value={searchOptions.alpha}
                        onChange={(value) => setSearchOptions({ ...searchOptions, alpha: value })}
                      />
                    </div>
                    <div>
                      <Space>
                        <Switch
                          size="small"
                          checked={searchOptions.rerank}
                          onChange={(checked) => setSearchOptions({ ...searchOptions, rerank: checked })}
                        />
                        <Text>启用重排 (Rerank)</Text>
                      </Space>
                    </div>
                    {searchOptions.rerank && (
                      <div>
                        <Text>重排候选数: {searchOptions.rerankTopN}</Text>
                        <Slider
                          min={5}
                          max={50}
                          value={searchOptions.rerankTopN}
                          onChange={(value) => setSearchOptions({ ...searchOptions, rerankTopN: value })}
                        />
                      </div>
                    )}
                  </Space>
                </Panel>
              </Collapse>

              <Button
                type="primary"
                icon={<SearchOutlined />}
                onClick={handleSearch}
                loading={searching}
              >
                搜索
              </Button>
            </Space>

            {/* Search Results */}
            {searchResults.length > 0 && (
              <div style={{ marginTop: 24 }}>
                <Divider orientation="left">
                  找到 {searchResults.length} 条相关结果
                </Divider>
                <List
                  size="small"
                  dataSource={searchResults}
                  style={{ maxHeight: 400, overflow: "auto" }}
                  renderItem={(item) => (
                    <List.Item
                      style={{ cursor: "pointer" }}
                      onClick={() => showDetail(item)}
                    >
                      <List.Item.Meta
                        avatar={<FileTextOutlined />}
                        title={
                          <Text ellipsis style={{ maxWidth: 600 }}>
                            {item.text}
                          </Text>
                        }
                        description={
                          <Space size="small">
                            <Tag>距离: {item.distance.toFixed(4)}</Tag>
                            <Tag>Chunk: {item.metadata.chunk_id}</Tag>
                          </Space>
                        }
                      />
                    </List.Item>
                  )}
                />
              </div>
            )}

            {searchResults.length === 0 && searchQuery && !searching && (
              <Text type="secondary" style={{ marginTop: 16, display: "block" }}>
                未找到相关结果
              </Text>
            )}
          </Card>
        </>
      )}

      {/* Detail Modal */}
      <Modal
        title="文档片段详情"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={null}
        width={700}
      >
        {selectedDoc && (
          <div>
            <p><Text strong>Chunk ID:</Text> {selectedDoc.metadata.chunk_id}</p>
            <p><Text strong>Document ID:</Text> {selectedDoc.metadata.document_id}</p>
            <p><Text strong>距离得分:</Text> {selectedDoc.distance.toFixed(6)}</p>
            <div style={{ marginTop: 16 }}>
              <Text strong>内容:</Text>
              <div
                style={{
                  marginTop: 8,
                  padding: 12,
                  background: "#f5f5f5",
                  borderRadius: 4,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  fontFamily: "monospace",
                }}
              >
                {selectedDoc.text}
              </div>
            </div>
          </div>
        )}
      </Modal>

      {/* Create Modal */}
      <Modal
        title="创建知识库"
        open={modalVisible}
        onCancel={() => {
          setModalVisible(false);
          form.resetFields();
        }}
        footer={null}
      >
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: "请输入名称" }]}
          >
            <Input placeholder="请输入知识库名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="请输入描述" />
          </Form.Item>
          {/* Embedding 模型 — sourced from model_configs (T18 component),
              not hardcoded. `embedding_model_config_id` is the FK the
              backend now requires on create. `onLoaded` pushes the
              loaded list up so the useEffect above can auto-default
              the field when the modal opens. */}
          <Form.Item
            name="embedding_model_config_id"
            label="Embedding 模型"
            rules={[{ required: true, message: "请选择 Embedding 模型" }]}
          >
            <EmbeddingModelSelect onLoaded={setLoadedEmbeddingModels} />
          </Form.Item>
          {/* 默认解析器 */}
          <Form.Item name="default_parser" label="默认解析器" initialValue="general">
            <Select>
              <Select.Option value="general">通用文档</Select.Option>
              <Select.Option value="paper">学术论文</Select.Option>
              <Select.Option value="qa">问答文档</Select.Option>
              <Select.Option value="table">表格文档</Select.Option>
              <Select.Option value="manual">用户手册</Select.Option>
              <Select.Option value="laws">法律文档</Select.Option>
            </Select>
          </Form.Item>
          {/* 分块大小和重叠 */}
          <Space>
            <Form.Item name="chunk_size" label="分块大小" initialValue={500}>
              <InputNumber min={100} max={2000} />
            </Form.Item>
            <Form.Item name="chunk_overlap" label="重叠token" initialValue={50}>
              <InputNumber min={0} max={200} />
            </Form.Item>
          </Space>
          {/* 搜索权重 Collapse */}
          <Collapse ghost>
            <Panel header="搜索权重配置" key="weights">
              <Space direction="vertical" style={{ width: '100%' }}>
                <div>
                  <Text>title: {searchWeights.title}</Text>
                  <Slider min={0} max={100} value={searchWeights.title} onChange={(v) => setSearchWeights({...searchWeights, title: v})} />
                </div>
                <div>
                  <Text>important_kw: {searchWeights.important_kw}</Text>
                  <Slider min={0} max={100} value={searchWeights.important_kw} onChange={(v) => setSearchWeights({...searchWeights, important_kw: v})} />
                </div>
                <div>
                  <Text>question_kw: {searchWeights.question_kw}</Text>
                  <Slider min={0} max={100} value={searchWeights.question_kw} onChange={(v) => setSearchWeights({...searchWeights, question_kw: v})} />
                </div>
                <div>
                  <Text>text: {searchWeights.text}</Text>
                  <Slider min={0} max={100} value={searchWeights.text} onChange={(v) => setSearchWeights({...searchWeights, text: v})} />
                </div>
              </Space>
            </Panel>
          </Collapse>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                创建
              </Button>
              <Button onClick={() => setModalVisible(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* Edit Modal */}
      <Modal
        title={`编辑知识库: ${editingKB?.name || ''}`}
        open={editModalVisible}
        onCancel={() => {
          setEditModalVisible(false);
          editForm.resetFields();
        }}
        footer={null}
        width={600}
      >
        <Form form={editForm} layout="vertical" onFinish={handleUpdate}>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: "请输入名称" }]}
          >
            <Input placeholder="请输入知识库名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="请输入描述" />
          </Form.Item>
          {/* Embedding 模型 — locked once a KB is created. The
              EmbeddingModelSelect renders the disabled hint itself
              when `disabled` is true. */}
          <Form.Item name="embedding_model_config_id" label="Embedding 模型">
            <EmbeddingModelSelect disabled />
          </Form.Item>
          {/* 默认解析器 */}
          <Form.Item name="default_parser" label="默认解析器">
            <Select>
              <Select.Option value="general">通用文档</Select.Option>
              <Select.Option value="paper">学术论文</Select.Option>
              <Select.Option value="qa">问答文档</Select.Option>
              <Select.Option value="table">表格文档</Select.Option>
              <Select.Option value="manual">用户手册</Select.Option>
              <Select.Option value="laws">法律文档</Select.Option>
            </Select>
          </Form.Item>
          {/* 分块大小和重叠 */}
          <Space>
            <Form.Item name="chunk_size" label="分块大小">
              <InputNumber min={100} max={2000} />
            </Form.Item>
            <Form.Item name="chunk_overlap" label="重叠token">
              <InputNumber min={0} max={200} />
            </Form.Item>
          </Space>
          {/* 搜索权重 Collapse */}
          <Collapse ghost>
            <Panel header="搜索权重配置" key="weights">
              <Space direction="vertical" style={{ width: '100%' }}>
                <div>
                  <Text>title: {editSearchWeights.title}</Text>
                  <Slider min={0} max={100} value={editSearchWeights.title} onChange={(v) => setEditSearchWeights({...editSearchWeights, title: v})} />
                </div>
                <div>
                  <Text>important_kw: {editSearchWeights.important_kw}</Text>
                  <Slider min={0} max={100} value={editSearchWeights.important_kw} onChange={(v) => setEditSearchWeights({...editSearchWeights, important_kw: v})} />
                </div>
                <div>
                  <Text>question_kw: {editSearchWeights.question_kw}</Text>
                  <Slider min={0} max={100} value={editSearchWeights.question_kw} onChange={(v) => setEditSearchWeights({...editSearchWeights, question_kw: v})} />
                </div>
                <div>
                  <Text>text: {editSearchWeights.text}</Text>
                  <Slider min={0} max={100} value={editSearchWeights.text} onChange={(v) => setEditSearchWeights({...editSearchWeights, text: v})} />
                </div>
              </Space>
            </Panel>
          </Collapse>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                保存
              </Button>
              <Button onClick={() => setEditModalVisible(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* Document List Modal */}
      <Modal
        title={`文档列表: ${docListKB?.name || ''}`}
        open={docListModalVisible}
        onCancel={() => setDocListModalVisible(false)}
        footer={null}
        width={800}
      >
        {docListLoading ? (
          <Text type="secondary">加载中...</Text>
        ) : docList.length === 0 ? (
          <Text type="secondary">暂无文档</Text>
        ) : (
          <List
            size="small"
            dataSource={docList}
            renderItem={(doc) => {
              const docType = doc.doc_metadata?.doc_type;
              const retriable = ["pending", "queued", "processing"].includes(doc.status);
              return (
              <List.Item
                data-doc-id={String(doc.id)}
                actions={[
                  doc.status === "completed" && (
                    <Button
                      key="view-chunks"
                      size="small"
                      type="link"
                      icon={<BarsOutlined />}
                      onClick={() => handleViewChunks(doc)}
                    >
                      查看分块
                    </Button>
                  ),
                  <Button
                    key="rechunk"
                    size="small"
                    type="link"
                    icon={<AppstoreOutlined />}
                    onClick={() => handleRechunk(doc)}
                  >
                    重新分块
                  </Button>,
                  retriable && (
                    <Popconfirm
                      key="retry"
                      title="确定要重新处理此文档吗？之前的分块会被清除。"
                      onConfirm={() => handleRetry(doc)}
                    >
                      <Button
                        size="small"
                        type="link"
                        icon={<RedoOutlined />}
                        loading={retryingDocId === doc.id}
                      >
                        重试
                      </Button>
                    </Popconfirm>
                  ),
                  <DeleteDocumentAction
                    loading={deletingDocId === doc.id}
                    onConfirm={() => handleDeleteDocument(doc)}
                  />,
                  docType && (
                    <Tag key="type" color="blue">
                      {parserTypes.find((t: ParserType) => t.type === docType)?.label || docType}
                    </Tag>
                  ),
                  <Tag key="status" color={doc.status === "completed" ? "green" : doc.status === "failed" ? "red" : doc.status === "queued" ? "purple" : "orange"}>
                    {doc.status === "completed" ? "已完成" : doc.status === "failed" ? "失败" : doc.status === "queued" ? "排队中" : "处理中"}
                  </Tag>,
                  doc.chunk_count && <Text key="chunks" type="secondary">分块: {doc.chunk_count}</Text>,
                  <Text key="size" type="secondary">{formatFileSize(doc.file_size)}</Text>,
                ]}
              >
                <List.Item.Meta
                  avatar={<FileTextOutlined />}
                  title={<Text>{doc.filename}</Text>}
                  description={`上传时间: ${doc.created_at}`}
                />
              </List.Item>
              );
            }}
          />
        )}
      </Modal>

      {/* View Chunks Modal */}
      <Modal
        title={`分块详情: ${chunksDoc?.filename || ''}`}
        open={chunksModalOpen}
        onCancel={() => setChunksModalOpen(false)}
        footer={null}
        width={800}
      >
        {chunksDoc && (
          <>
            <div style={{ marginBottom: 12 }}>
              <Text type="secondary">
                共 {chunksDoc.chunk_count ?? 0} 个分块
              </Text>
            </div>
            <Table<DocumentChunk>
              size="small"
              dataSource={chunks}
              rowKey="id"
              loading={chunksLoading}
              pagination={{
                current: chunksPage,
                pageSize: chunksPageSize,
                total: chunksDoc.chunk_count ?? 0,
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 50, 100],
                onChange: (p, ps) => {
                  setChunksPage(p);
                  setChunksPageSize(ps);
                  fetchChunks(chunksDoc.id, p, ps);
                },
              }}
              columns={[
                { title: "#", dataIndex: "chunk_index", width: 60 },
                {
                  title: "内容",
                  dataIndex: "content",
                  render: (text: string) => (
                    <pre
                      style={{
                        margin: 0,
                        maxHeight: 120,
                        overflow: "auto",
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                        fontFamily: "monospace",
                        fontSize: 12,
                        background: "#f5f5f5",
                        padding: 8,
                        borderRadius: 4,
                      }}
                    >
                      {text}
                    </pre>
                  ),
                },
                {
                  title: "长度",
                  dataIndex: "content",
                  width: 80,
                  render: (text: string) => <Text type="secondary">{text.length}</Text>,
                },
                {
                  title: "向量ID",
                  dataIndex: "vector_id",
                  width: 120,
                  render: (vid?: string) =>
                    vid ? (
                      <Text type="secondary" style={{ fontSize: 11 }} copyable>
                        {vid.length > 8 ? `…${vid.slice(-8)}` : vid}
                      </Text>
                    ) : (
                      <Text type="secondary">-</Text>
                    ),
                },
              ]}
            />
          </>
        )}
      </Modal>

      {/* Re-chunk Modal */}
      <Modal
        title={`重新分块: ${rechunkDoc?.filename || ''}`}
        open={rechunkModalOpen}
        onCancel={() => {
          setRechunkModalOpen(false);
          rechunkForm.resetFields();
        }}
        footer={null}
        width={560}
      >
        <Form
          form={rechunkForm}
          layout="vertical"
          onFinish={handleRechunkSubmit}
        >
          <Form.Item
            name="chunking_strategy"
            label="分块策略"
            rules={[{ required: true, message: "请选择分块策略" }]}
          >
            <Select
              options={[
                { value: "fixed", label: "固定长度" },
                { value: "semantic", label: "语义分块" },
                { value: "document_structure", label: "文档结构" },
              ]}
            />
          </Form.Item>
          <Form.Item name="doc_type" label="文档类型">
            <Select
              allowClear
              placeholder="沿用原文档类型"
              options={parserTypes.map((t: ParserType) => ({
                value: t.type,
                label: t.label,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="chunk_size"
            label="分块大小 (chunk_size)"
            rules={[{ required: true, message: "请输入分块大小" }]}
          >
            <InputNumber min={100} max={2000} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item
            name="chunk_overlap"
            label="重叠 token (chunk_overlap)"
            rules={[{ required: true, message: "请输入重叠 token" }]}
          >
            <InputNumber min={0} max={200} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button
                type="primary"
                htmlType="submit"
                loading={rechunkSubmitting}
              >
                提交
              </Button>
              <Button
                onClick={() => {
                  setRechunkModalOpen(false);
                  rechunkForm.resetFields();
                }}
              >
                取消
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* M28: 删 KB 失败时弹的 blockers Modal。toast 3 秒就消失,
          用户根本来不及想「我该去哪个 agent 解绑」,改成持久 Modal。 */}
      <Modal
        title="无法删除知识库"
        open={blockerModal.visible}
        onCancel={() => setBlockerModal((prev) => ({ ...prev, visible: false }))}
        footer={[
          <Button
            key="ok"
            type="primary"
            onClick={() => setBlockerModal((prev) => ({ ...prev, visible: false }))}
          >
            知道了
          </Button>,
        ]}
      >
        <p style={{ marginBottom: 16 }}>{blockerModal.message}</p>

        {blockerModal.agents.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <Typography.Text strong>引用此知识库的 Agent</Typography.Text>
            <List
              size="small"
              style={{ marginTop: 4 }}
              dataSource={blockerModal.agents}
              renderItem={(a) => (
                <List.Item>
                  <span>
                    {a.name}
                    <Typography.Text type="secondary"> · id={a.id}</Typography.Text>
                  </span>
                </List.Item>
              )}
            />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              请到 Agent 详情页的知识库区域取消绑定,或删除该 Agent。
            </Typography.Text>
          </div>
        )}

        {blockerModal.documents.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <Typography.Text strong>关联的文档</Typography.Text>
            <List
              size="small"
              style={{ marginTop: 4 }}
              dataSource={blockerModal.documents}
              renderItem={(d) => (
                <List.Item>
                  <span>
                    {d.filename}
                    <Typography.Text type="secondary"> · id={d.id}</Typography.Text>
                  </span>
                </List.Item>
              )}
            />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              请先删除这些文档(回到本页打开「文档列表」可批量删)。
            </Typography.Text>
          </div>
        )}

        {blockerModal.truncated && (
          <Typography.Text type="warning" style={{ fontSize: 12 }}>
            列表已截断(后端每次最多返回 10 条),实际 blocker 数量可能更多。
          </Typography.Text>
        )}
      </Modal>
    </div>
  );
}
