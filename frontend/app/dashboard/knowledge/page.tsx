"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import {
  Layout,
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
  Breadcrumb,
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
  SwapOutlined,
  TeamOutlined,
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
// M38.2: workspace + folder navigation + 3 个 modal。
import WorkspaceTree from "@/components/knowledge/WorkspaceTree";
import CreateWorkspaceModal from "@/components/knowledge/CreateWorkspaceModal";
import CreateFolderModal from "@/components/knowledge/CreateFolderModal";
import MoveDocumentModal from "@/components/knowledge/MoveDocumentModal";
// M40.1 Phase 1: useWorkspaceTree hook —— workspace/folder/rbac 状态 + 4 modal + 8 handler。
import { useWorkspaceTree } from "@/app/dashboard/knowledge/hooks/useWorkspaceTree";
// M40.1 Phase 2: useKnowledgeList hook —— KB list 状态 + CRUD + blocker modal。
import { useKnowledgeList } from "@/app/dashboard/knowledge/hooks/useKnowledgeList";
// M40.1 Phase 3: useDocumentUpload hook —— 上传 mutation + doc type picker。
import { useDocumentUpload } from "@/app/dashboard/knowledge/hooks/useDocumentUpload";
// M38.2.x v2: workspace RBAC members 管理 + useCanI gate
import { WorkspaceMembersModal } from "@/components/knowledge/WorkspaceMembersModal";
import { useCanI } from "@/hooks/useWorkspacePermissions";

const { TextArea } = Input;
const { Text } = Typography;
const { Panel } = Collapse;
const { Sider, Content } = Layout;

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
  // ──────────── M40.1 Phase 2: useKnowledgeList hook ────────────
  // KB list 状态 + CRUD + blocker modal 全部搬进 hook。下面只保留
  // document / search / upload / modal 状态(Phase 3~6 拆)。

  // Search state(Phase 5 useDocumentSearch 接管)
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  // Documents state(Phase 4 useDocumentList 接管)
  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState<SearchResult | null>(null);

  // M40.1 Phase 3: 上传 state 搬到 useDocumentUpload hook。

  // Search options state(Phase 5 useDocumentSearch 接管)
  const [searchOptions, setSearchOptions] = useState({
    k: 5,
    alpha: 0.5,
    rerank: true,
    rerankTopN: 10,
    fieldWeights: "",
  });

  // Embedding models 缓存 —— EmbeddingModelSelect.onLoaded 回调写到这。
  // useKnowledgeList 通过 args.loadedEmbeddingModels 读取(form auto-default 用)。
  // 这里 page 层维护 cache 是为了避免 hook 跟组件内 fetch 抢。
  const [loadedEmbeddingModels, setLoadedEmbeddingModels] = useState<
    ModelConfig[]
  >([]);

  // Document list modal state(Phase 4 useDocumentList 接管)
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

  // M40.1 Phase 2: blocker modal state 搬到 useKnowledgeList hook。

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

  // M40.1 Phase 1: workspace/folder/rbac 状态全部搬到 useWorkspaceTree hook。
  // 这里只剩 KB / document / search 相关的 state。

  // Fetch parser types
  const { data: parserTypesData } = useQuery({
    queryKey: ["parserTypes"],
    queryFn: () => knowledgeApi.getParserTypes(),
  });
  const parserTypes = parserTypesData?.data?.data?.parser_types || [];

  const queryClient = useQueryClient();

  const searchParams = useSearchParams();

  // M40.1 Phase 2: useKnowledgeList hook —— KB 列表 + CRUD + blocker modal。
  // 必须在 useWorkspaceTree 之前创建:ws.selectedKB / ws.onKbChange 引用 kb。
  // selectedWorkspaceId 通过 useRef 同步:kb init 时 ws 还没建,直接读 ws.selectedWorkspaceId
  // 是 null(handler closure 拿到 init 时刻的值)。
  const wsRef = useRef<number | null>(null);
  const kb = useKnowledgeList({
    selectedWorkspaceId: wsRef.current,
    loadedEmbeddingModels,
    onKbChangeCleanup: (newKB) => {
      setSearchResults([]);
      setSearchQuery("");
      setDocuments([]);
    },
    onKbSelectFetchDocs: (kbId) => {
      fetchDocuments(kbId, null);
    },
  });

  // M40.1 Phase 1: workspace/folder navigation + 4 modal + 8 handler 集中到 hook。
  // ws.selectedKB 读 kb hook 持有的选中状态;ws.onKbChange 通过 kb.handleSelectKB
  // 转发给 kb hook(内部 setSelectedFolderId + onKbChangeCleanup + onKbSelectFetchDocs)。
  const ws = useWorkspaceTree({
    selectedKB: kb.selectedKB,
    onKbChange: (newKB) => {
      kb.handleSelectKB(newKB);
    },
  });
  // 同步 selectedWorkspaceId 给 kb hook(closure refresh)
  wsRef.current = ws.selectedWorkspaceId;

  // M40.1 Phase 3: useDocumentUpload hook —— upload mutation + doc type picker。
  // onUploadSuccess 触发 KB list badge 刷新 + 当前 KB 文档列表刷新。
  const up = useDocumentUpload({
    currentFolderId: ws.selectedFolderId,
    onUploadSuccess: (kbId) => {
      kb.refreshKbList();
      if (kb.selectedKB && kb.selectedKB.id === kbId) {
        queryClient.invalidateQueries({ queryKey: ["documents", kbId] });
        fetchDocuments(kbId);
      }
    },
  });

  useEffect(() => {
    // Subscribe to incoming notifications; refetch the current KB's doc
    // list when a doc-related notification for that KB arrives.
    const unsub = useNotificationsStore.subscribe((state, prev) => {
      if (state.items === prev.items) return;
      const newest = state.items[0];
      if (!newest) return;
      if (
        newest.resource_type === "document" &&
        kb.selectedKB !== null &&
        newest.metadata?.kb_id === kb.selectedKB.id &&
        // Only react to length growth (WS push, refetchUnread backfill, loadMore).
        // Pure state swaps like markRead/markAllRead/reset don't change length,
        // so they don't trigger a refetch.
        prev.items.length < state.items.length
      ) {
        // M38.2: 通知触发的刷新也得带上 folder 过滤 —— 否则在 folder 视图下
        // 收到的 doc 通知会污染显示成「全部文档」。
        fetchDocuments(kb.selectedKB.id);
      }
    });
    return () => { unsub(); };
    // M40.1: ws.selectedFolderId 进入依赖 —— 切换 folder 时也要重订一次订阅
    // (虽然 subscribe 本身不需要,但保持 deps 干净,eslint 不报警)。
  }, [kb.selectedKB?.id, ws.selectedFolderId]);

  // M40.1: sidebar 切 folder → 重新拉文档。hook 化前由 handleSelectFolder 内联调
  // fetchDocuments,hook 化后 hook 不持有 page 层 fetchDocuments,改用 effect 监听
  // folder 变化。Phase 2 useDocumentList 接管后会改走 query,本 effect 临时作为桥接。
  useEffect(() => {
    if (kb.selectedKB) {
      fetchDocuments(kb.selectedKB.id, ws.selectedFolderId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ws.selectedFolderId, kb.selectedKB?.id]);

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

  // M40.1 Phase 3: uploadMutation + handleUpload 搬到 useDocumentUpload hook。

  // M40.1 Phase 2: kb.refreshKbList / kb.handleSelectKB / kb.handleCreate / kb.handleDelete /
// kb.handleEdit / kb.handleUpdate 全部搬到 useKnowledgeList hook。
// 下面的 fetchDocuments 仍在 page 层(Phase 4 useDocumentList 接管),
// 通过 args.onKbSelectFetchDocs 传给 hook 做 KB 切换时拉文档用。

  const fetchDocuments = async (kbId: number, folderId?: number | null) => {
    setLoadingDocs(true);
    try {
      // M40.1: folder 来自 useWorkspaceTree。null = 不过滤(全部),number = 那个 folder。
      // folderId 优先用入参,fallback 到 hook state —— sidebar 切换 folder 时入参
      // 是新值,hook state 还是旧值,避免 stale closure 拿到错的 folder_id。
      const fId = folderId !== undefined ? folderId : ws.selectedFolderId;
      const response = await knowledgeApi.getDocuments(kbId, fId ?? undefined);
      if (response.data.code === 200) {
        setDocuments(response.data.data || []);
      }
    } catch (error) {
      message.error("加载文档列表失败");
    } finally {
      setLoadingDocs(false);
    }
  };

  // M40.1 Phase 3: handleUpload 搬到 useDocumentUpload hook。

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
        if (kb.selectedKB) {
          await fetchDocuments(kb.selectedKB.id);
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
        // list in sync via the next kb.refreshKbList().
        if (docListModalVisible && docListKB) {
          await handleViewDocs(docListKB);
          if (kb.selectedKB && kb.selectedKB.id !== docListKB.id) {
            await fetchDocuments(kb.selectedKB.id);
          }
        } else if (kb.selectedKB) {
          await fetchDocuments(kb.selectedKB.id);
        }
        // KB row's `document_count` is derived in the service layer;
        // the manual kb.refreshKbList() refetch below updates the badge.
        await kb.refreshKbList();
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
    const parentKB = doc.knowledge_base_id
      ? kb.data.find((k) => k.id === doc.knowledge_base_id) || kb.selectedKB
      : null;
    const existingDocType = doc.doc_metadata?.doc_type;
    rechunkForm.setFieldsValue({
      chunking_strategy: "fixed",
      chunk_size: (parentKB as any)?.chunk_size ?? 500,
      chunk_overlap: (parentKB as any)?.chunk_overlap ?? 50,
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
        if (kb.selectedKB) {
          await fetchDocuments(kb.selectedKB.id);
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
    if (!kb.selectedKB || !searchQuery.trim()) {
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
      const response = await knowledgeApi.search(kb.selectedKB.id, searchQuery, options);
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
            type={kb.selectedKB?.id === record.id ? "primary" : "default"}
            icon={<SearchOutlined />}
            onClick={() => kb.handleSelectKB(kb.selectedKB?.id === record.id ? null : record)}
          >
            {kb.selectedKB?.id === record.id ? "取消选择" : "查看"}
          </Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => kb.handleEdit(record)}>
            编辑
          </Button>
          <Upload
            showUploadList={false}
            beforeUpload={(file) => up.handleUpload(record.id, file)}
          >
            <Button
              size="small"
              icon={<UploadOutlined />}
              loading={up.uploadMutation.isPending && up.uploadMutation.variables?.kbId === record.id}
            >
              上传
            </Button>
          </Upload>
          <Popconfirm
            title="确认删除?"
            onConfirm={() => kb.handleDelete(record.id)}
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
    <Layout style={{ minHeight: "calc(100vh - 64px)", background: "#fff" }}>
      {/* M38.2: workspace → KB → folder 侧边栏导航 */}
      <Sider
        width={260}
        theme="light"
        style={{ borderRight: "1px solid #f0f0f0", overflow: "auto" }}
      >
        <WorkspaceTree
          selectedWorkspaceId={ws.selectedWorkspaceId}
          selectedKbId={kb.selectedKB?.id ?? null}
          selectedFolderId={ws.selectedFolderId}
          treesByWorkspace={ws.treesByWorkspace}
          loading={ws.workspaceTreeLoading}
          // M38.2 UX: 默认展开所有层级 —— workspace 数量少,
          // 一次性看到 workspace → KB → folder 结构减少认知成本。
          defaultExpandAll
          onCreateWorkspace={() => ws.setCreateWsOpen(true)}
          onCreateFolder={(_wsId, kbId) => {
            // Sider 入口:KB 必须先选中才能新建 folder。
            if (!kb.selectedKB || kb.selectedKB.id !== kbId) {
              knowledgeApi.get(kbId).then((r) => {
                if (r.data.code === 200 && r.data.data) ws.handleSelectKb(null, kbId);
              });
            }
            ws.setCreateFolderOpen(true);
          }}
          onSelectWorkspace={ws.handleSelectWorkspace}
          onSelectKb={ws.handleSelectKb}
          onSelectFolder={ws.handleSelectFolder}
          // 2.1 C.12: drag-drop 移动 KB / folder
          onMoveKb={ws.handleMoveKbDrag}
          onMoveFolder={ws.handleMoveFolderDrag}
        />
      </Sider>
      <Content style={{ padding: 24, overflow: "auto" }}>
        {/* M38.2: breadcrumb —— workspace › KB › folder 名 */}
        <Breadcrumb
          style={{ marginBottom: 16 }}
          items={[
            {
              title:
                ws.selectedWorkspaceId != null && ws.selectedWorkspaceId > 0
                  ? ws.workspaces.find((w) => w.id === ws.selectedWorkspaceId)?.name ||
                    `Workspace #${ws.selectedWorkspaceId}`
                  : "未分组",
            },
            ...(kb.selectedKB
                ? [
                    {
                      title: (
                        <a
                          onClick={(e) => {
                            e.preventDefault();
                            ws.setSelectedFolderId(null);
                            if (kb.selectedKB) fetchDocuments(kb.selectedKB.id);
                          }}
                          href="#"
                        >
                          {kb.selectedKB.name}
                        </a>
                      ),
                    },
                  ]
                : []),
            ...(ws.selectedFolderId != null
              ? [
                  {
                    title: `Folder #${ws.selectedFolderId}`,
                  },
                ]
              : []),
            ...(kb.selectedKB && ws.selectedFolderId == null
              ? [{ title: "KB 根目录" }]
              : []),
          ]}
        />
      {/* Knowledge Base List */}
      <Card title="知识库列表" style={{ marginBottom: 16 }}>
        <div style={{ marginBottom: 16, display: "flex", gap: 8, alignItems: "center" }}>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => kb.setModalVisible(true)}
          >
            创建知识库
          </Button>
          {ws.selectedWorkspaceId != null && ws.selectedWorkspaceId > 0 && (
            <WorkspaceMembersButton
              workspaceId={ws.selectedWorkspaceId}
              workspaceName={
                ws.workspaces.find((w) => w.id === ws.selectedWorkspaceId)?.name ??
                `Workspace #${ws.selectedWorkspaceId}`
              }
              currentUserId={ws.currentUserId}
              currentOwnerId={
                ws.workspaces.find((w) => w.id === ws.selectedWorkspaceId)?.owner_id ?? 0
              }
              onClick={() => ws.setMembersOpen(true)}
            />
          )}
        </div>
        <Table
          columns={columns}
          dataSource={kb.data}
          rowKey="id"
          loading={kb.loading}
          pagination={{
            current: kb.page,
            pageSize: kb.pageSize,
            total: kb.total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => {
              kb.setPage(p);
              kb.setPageSize(ps);
            },
          }}
          size="small"
        />
      </Card>

      {/* Selected KB Detail and Documents */}
      {kb.selectedKB && (
        <>
          <Card title={`知识库详情: ${kb.selectedKB.name}`} style={{ marginBottom: 16 }}>
            <p><Text strong>ID:</Text> {kb.selectedKB.id}</p>
            <p><Text strong>描述:</Text> {kb.selectedKB.description || "无"}</p>
            <p><Text strong>Embedding模型:</Text> {kb.selectedKB.embedding_model}</p>
            <p><Text strong>默认解析器:</Text> {
              (kb.selectedKB as any).default_parser ?
                (parserTypes.find((t: any) => t.type === (kb.selectedKB as any).default_parser)?.label || (kb.selectedKB as any).default_parser)
                : "通用文档"
            }</p>
            <p><Text strong>分块配置:</Text> 块大小 {(kb.selectedKB as any).chunk_size || 500} / 重叠 {(kb.selectedKB as any).chunk_overlap || 50}</p>
            <p><Text strong>状态:</Text> <Tag color={kb.selectedKB.status === "active" ? "green" : "default"}>{kb.selectedKB.status}</Tag></p>
            <p><Text strong>创建时间:</Text> {kb.selectedKB.created_at}</p>
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
                          value={up.selectedDocType || undefined}
                          onChange={(value) => up.setSelectedDocType(value || "")}
                          options={parserTypes.map((t: ParserType) => ({
                            label: t.label,
                            value: t.type,
                          }))}
                        />
                        <Upload
                          showUploadList={false}
                          beforeUpload={(file) => {
                            if (kb.selectedKB) up.handleUpload(kb.selectedKB.id, file);
                            return false;
                          }}
                        >
                          <Button
                            size="small"
                            icon={<UploadOutlined />}
                            loading={up.uploadMutation.isPending && up.uploadMutation.variables?.kbId === kb.selectedKB.id}
                          >
                            上传文档
                          </Button>
                        </Upload>
                        {/* M38.2: 当前 KB 下新建 folder —— 没选中 KB 时不显示 */}
                        <Button
                          size="small"
                          icon={<PlusOutlined />}
                          onClick={() => ws.setCreateFolderOpen(true)}
                        >
                          新建 folder
                        </Button>
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
                                // M38.2: 移动文档到其他 folder / KB 根
                                <Button
                                  key="move"
                                  size="small"
                                  type="link"
                                  icon={<SwapOutlined />}
                                  onClick={() => {
                                    ws.setMovingDoc(doc);
                                    ws.setMoveDocOpen(true);
                                  }}
                                >
                                  移动
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
                  children: <FAQTab kbId={kb.selectedKB.id} />,
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
        open={kb.modalVisible}
        onCancel={() => {
          kb.setModalVisible(false);
          kb.form.resetFields();
        }}
        footer={null}
      >
        <Form form={kb.form} layout="vertical" onFinish={kb.handleCreate}>
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
                  <Text>title: {kb.searchWeights.title}</Text>
                  <Slider min={0} max={100} value={kb.searchWeights.title} onChange={(v) => kb.setSearchWeights({...kb.searchWeights, title: v})} />
                </div>
                <div>
                  <Text>important_kw: {kb.searchWeights.important_kw}</Text>
                  <Slider min={0} max={100} value={kb.searchWeights.important_kw} onChange={(v) => kb.setSearchWeights({...kb.searchWeights, important_kw: v})} />
                </div>
                <div>
                  <Text>question_kw: {kb.searchWeights.question_kw}</Text>
                  <Slider min={0} max={100} value={kb.searchWeights.question_kw} onChange={(v) => kb.setSearchWeights({...kb.searchWeights, question_kw: v})} />
                </div>
                <div>
                  <Text>text: {kb.searchWeights.text}</Text>
                  <Slider min={0} max={100} value={kb.searchWeights.text} onChange={(v) => kb.setSearchWeights({...kb.searchWeights, text: v})} />
                </div>
              </Space>
            </Panel>
          </Collapse>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                创建
              </Button>
              <Button onClick={() => kb.setModalVisible(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* Edit Modal */}
      <Modal
        title={`编辑知识库: ${kb.editingKB?.name || ''}`}
        open={kb.editModalVisible}
        onCancel={() => {
          kb.setEditModalVisible(false);
          kb.editForm.resetFields();
        }}
        footer={null}
        width={600}
      >
        <Form form={kb.editForm} layout="vertical" onFinish={kb.handleUpdate}>
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
                  <Text>title: {kb.editSearchWeights.title}</Text>
                  <Slider min={0} max={100} value={kb.editSearchWeights.title} onChange={(v) => kb.setEditSearchWeights({...kb.editSearchWeights, title: v})} />
                </div>
                <div>
                  <Text>important_kw: {kb.editSearchWeights.important_kw}</Text>
                  <Slider min={0} max={100} value={kb.editSearchWeights.important_kw} onChange={(v) => kb.setEditSearchWeights({...kb.editSearchWeights, important_kw: v})} />
                </div>
                <div>
                  <Text>question_kw: {kb.editSearchWeights.question_kw}</Text>
                  <Slider min={0} max={100} value={kb.editSearchWeights.question_kw} onChange={(v) => kb.setEditSearchWeights({...kb.editSearchWeights, question_kw: v})} />
                </div>
                <div>
                  <Text>text: {kb.editSearchWeights.text}</Text>
                  <Slider min={0} max={100} value={kb.editSearchWeights.text} onChange={(v) => kb.setEditSearchWeights({...kb.editSearchWeights, text: v})} />
                </div>
              </Space>
            </Panel>
          </Collapse>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                保存
              </Button>
              <Button onClick={() => kb.setEditModalVisible(false)}>取消</Button>
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
                  // M38.2: 文档列表 modal 也支持移动
                  <Button
                    key="move"
                    size="small"
                    type="link"
                    icon={<SwapOutlined />}
                    onClick={() => {
                      ws.setMovingDoc(doc);
                      ws.setMoveDocOpen(true);
                    }}
                  >
                    移动
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
        open={kb.blockerModal.visible}
        onCancel={() => kb.setBlockerModal((prev) => ({ ...prev, visible: false }))}
        footer={[
          <Button
            key="ok"
            type="primary"
            onClick={() => kb.setBlockerModal((prev) => ({ ...prev, visible: false }))}
          >
            知道了
          </Button>,
        ]}
      >
        <p style={{ marginBottom: 16 }}>{kb.blockerModal.message}</p>

        {kb.blockerModal.agents.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <Typography.Text strong>引用此知识库的 Agent</Typography.Text>
            <List
              size="small"
              style={{ marginTop: 4 }}
              dataSource={kb.blockerModal.agents}
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

        {kb.blockerModal.documents.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <Typography.Text strong>关联的文档</Typography.Text>
            <List
              size="small"
              style={{ marginTop: 4 }}
              dataSource={kb.blockerModal.documents}
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

        {kb.blockerModal.truncated && (
          <Typography.Text type="warning" style={{ fontSize: 12 }}>
            列表已截断(后端每次最多返回 10 条),实际 blocker 数量可能更多。
          </Typography.Text>
        )}
      </Modal>
      </Content>

      {/* M38.2: 新建 workspace modal */}
      <CreateWorkspaceModal
        open={ws.createWsOpen}
        onCancel={() => ws.setCreateWsOpen(false)}
        onSubmit={ws.handleCreateWorkspace}
      />

      {/* M38.2: 新建 folder modal —— 当前选中 KB 必须存在。
          folders 给 tree 形态供 parent_choice 选择;defaultParentId 留给
          「右键新建子文件夹」等场景,当前 UI 暂不暴露入口。 */}
      {kb.selectedKB && (
        <CreateFolderModal
          open={ws.createFolderOpen}
          kbId={kb.selectedKB.id}
          folders={ws.folderTree}
          onCancel={() => ws.setCreateFolderOpen(false)}
          onSubmit={ws.handleCreateFolder}
        />
      )}

      {/* M38.2: 移动文档 modal —— 给「从当前 folder 移到别处」用。
          movingDoc 为 null 时 modal 不渲染,避免无效状态。 */}
      {ws.movingDoc && kb.selectedKB && (
        <MoveDocumentModal
          open={ws.moveDocOpen}
          documentId={ws.movingDoc.id}
          documentName={ws.movingDoc.filename}
          currentFolderId={ws.selectedFolderId}
          folders={ws.folderTree}
          onCancel={() => {
            ws.setMoveDocOpen(false);
            ws.setMovingDoc(null);
          }}
          onSubmit={ws.handleMoveDocument}
        />
      )}

      {/* M38.2.x v2: workspace 成员管理 modal —— 选中 workspace 时才显示。 */}
      {ws.selectedWorkspaceId != null && ws.selectedWorkspaceId > 0 && (
        <WorkspaceMembersModal
          open={ws.membersOpen}
          workspaceId={ws.selectedWorkspaceId}
          workspaceName={
            ws.workspaces.find((w) => w.id === ws.selectedWorkspaceId)?.name ??
            `Workspace #${ws.selectedWorkspaceId}`
          }
          currentUserId={ws.currentUserId}
          currentOwnerId={
            ws.workspaces.find((w) => w.id === ws.selectedWorkspaceId)?.owner_id ?? 0
          }
          onClose={() => ws.setMembersOpen(false)}
        />
      )}
    </Layout>
  );
}

// --- 成员管理按钮子组件 ------------------------------------------------

interface WorkspaceMembersButtonProps {
  workspaceId: number;
  workspaceName: string;
  currentUserId: number;
  currentOwnerId: number;
  onClick: () => void;
}

/**
 * 「成员」按钮 —— useCanI("workspace.manage_members") 决定 enabled。
 * owner 自动有 manage_members 权限(spec §6.5),但这里直接由 useCanI 处理。
 */
function WorkspaceMembersButton({
  workspaceId,
  onClick,
}: WorkspaceMembersButtonProps) {
  const canManage = useCanI("workspace.manage_members", workspaceId);
  return (
    <Button
      icon={<TeamOutlined />}
      disabled={!canManage}
      onClick={onClick}
    >
      成员管理
    </Button>
  );
}
