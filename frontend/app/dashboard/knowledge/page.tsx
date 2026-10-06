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
// M38.2: workspace + folder navigation + 3 个 modal。
import WorkspaceTree from "@/components/knowledge/WorkspaceTree";
import CreateWorkspaceModal from "@/components/knowledge/CreateWorkspaceModal";
import CreateFolderModal from "@/components/knowledge/CreateFolderModal";
import MoveDocumentModal from "@/components/knowledge/MoveDocumentModal";
// M40.1 Phase 6: KB CRUD + blocker / search / chunks 子组件拆分。
import CreateKBModal from "@/components/knowledge/CreateKBModal";
import EditKBModal from "@/components/knowledge/EditKBModal";
import BlockerModal from "@/components/knowledge/BlockerModal";
import SearchCard from "@/components/knowledge/SearchCard";
import ViewChunksModal from "@/components/knowledge/ViewChunksModal";
// M40.1 Phase 1: useWorkspaceTree hook —— workspace/folder/rbac 状态 + 4 modal + 8 handler。
import { useWorkspaceTree } from "@/app/dashboard/knowledge/hooks/useWorkspaceTree";
// M40.1 Phase 2: useKnowledgeList hook —— KB list 状态 + CRUD + blocker modal。
import { useKnowledgeList } from "@/app/dashboard/knowledge/hooks/useKnowledgeList";
// M40.1 Phase 3: useDocumentUpload hook —— 上传 mutation + doc type picker。
import { useDocumentUpload } from "@/app/dashboard/knowledge/hooks/useDocumentUpload";
// M40.1 Phase 4: useDocumentList hook —— documents + 重试/删除/分块/重新分块 + 通知订阅。
import { useDocumentList } from "@/app/dashboard/knowledge/hooks/useDocumentList";
// M40.1 Phase 5: useDocumentSearch hook —— 搜索 + 高级选项 + detail modal。
import {
  useDocumentSearch,
  type SearchResult,
} from "@/app/dashboard/knowledge/hooks/useDocumentSearch";
// M38.2.x v2: workspace RBAC members 管理 + useCanI gate
import { WorkspaceMembersModal } from "@/components/knowledge/WorkspaceMembersModal";
import { useCanI } from "@/hooks/useWorkspacePermissions";

const { TextArea } = Input;
const { Text } = Typography;
const { Panel } = Collapse;
const { Sider, Content } = Layout;

// SearchResult 类型搬到 useDocumentSearch hook 内并 export,page 层 import 复用。

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
  // upload 状态(Phase 3 拆)+ modal 状态(后续 fold 进 hook)。

  // M40.1 Phase 5: search state 全部搬到 useDocumentSearch hook。

  // Embedding models 缓存 —— EmbeddingModelSelect.onLoaded 回调写到这。
  // useKnowledgeList 通过 args.loadedEmbeddingModels 读取(form auto-default 用)。
  // 这里 page 层维护 cache 是为了避免 hook 跟组件内 fetch 抢。
  const [loadedEmbeddingModels, setLoadedEmbeddingModels] = useState<
    ModelConfig[]
  >([]);

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
    onKbChangeCleanup: (_newKB) => {
      // documents 已搬到 useDocumentList,hook 内 bridge effect 监听 selectedKB 变化自动 fetch;
      // searchResults / searchQuery 已在 useDocumentSearch hook 内通过 KB 切换 reset。
      void _newKB;
    },
    onKbSelectFetchDocs: (kbId) => {
      // 兼容 kb hook 接口 —— c1 hook 自己 effect 已响应 selectedKB 变化,
      // 这里 noop(否则会重复 fetchDocuments 一次)
      void kbId;
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
        c1.refreshDocuments();
      }
    },
  });

  // M40.1 Phase 4: useDocumentList hook —— documents + docList/chunks/rechunk modal + 通知订阅。
  // 在 up 之后:c1.documents.length / c1.docList.length 用于 deep-link effect。
  const c1 = useDocumentList({
    selectedKB: kb.selectedKB,
    selectedFolderId: ws.selectedFolderId,
    refreshKbList: kb.refreshKbList,
    allKBs: kb.data,
  });

  // M40.1 Phase 5: useDocumentSearch hook —— 搜索 query / options / results + detail modal。
  const s2 = useDocumentSearch({
    selectedKB: kb.selectedKB,
  });

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
  }, [docParam, c1.documents.length, c1.docList.length]);

  // M40.1 Phase 3: uploadMutation + handleUpload 搬到 useDocumentUpload hook。

  // M40.1 Phase 2: kb.refreshKbList / kb.handleSelectKB / kb.handleCreate / kb.handleDelete /
// kb.handleEdit / kb.handleUpdate 全部搬到 useKnowledgeList hook。
// M40.1 Phase 4:fetchDocuments / handleRetry / handleDeleteDocument / handleViewDocs /
// fetchChunks / handleViewChunks / handleRechunk / handleRechunkSubmit 全部搬到 useDocumentList hook。
// M40.1 Phase 5:handleSearch / showDetail 全部搬到 useDocumentSearch hook。

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
          onClick={() => c1.openDocList(record)}
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
                            if (kb.selectedKB) c1.refreshDocuments();
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
                      {c1.loadingDocs ? (
                        <Text type="secondary">加载中...</Text>
                      ) : c1.documents.length === 0 ? (
                        <Text type="secondary">暂无文档，请上传</Text>
                      ) : (
                        <List
                          size="small"
                          dataSource={c1.documents}
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
                                    onClick={() => c1.openChunksModal(doc)}
                                  >
                                    查看分块
                                  </Button>
                                ),
                                <Button
                                  key="rechunk"
                                  size="small"
                                  type="link"
                                  icon={<AppstoreOutlined />}
                                  onClick={() => c1.openRechunkModal(doc)}
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
                                    onConfirm={() => c1.handleRetry(doc)}
                                  >
                                    <Button
                                      size="small"
                                      type="link"
                                      icon={<RedoOutlined />}
                                      loading={c1.retryingDocId === doc.id}
                                    >
                                      重试
                                    </Button>
                                  </Popconfirm>
                                ),
                                <DeleteDocumentAction
                                  loading={c1.deletingDocId === doc.id}
                                  onConfirm={() => c1.handleDeleteDocument(doc)}
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
          <SearchCard
            searchQuery={s2.searchQuery}
            setSearchQuery={s2.setSearchQuery}
            searchOptions={s2.searchOptions}
            setSearchOptions={s2.setSearchOptions}
            searching={s2.searching}
            searchResults={s2.searchResults}
            handleSearch={s2.handleSearch}
            showDetail={s2.showDetail}
          />
        </>
      )}

      {/* Detail Modal */}
      <Modal
        title="文档片段详情"
        open={s2.detailModalVisible}
        onCancel={() => s2.setDetailModalVisible(false)}
        footer={null}
        width={700}
      >
        {s2.selectedDoc && (
          <div>
            <p><Text strong>Chunk ID:</Text> {s2.selectedDoc.metadata.chunk_id}</p>
            <p><Text strong>Document ID:</Text> {s2.selectedDoc.metadata.document_id}</p>
            <p><Text strong>距离得分:</Text> {s2.selectedDoc.distance.toFixed(6)}</p>
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
                {s2.selectedDoc.text}
              </div>
            </div>
          </div>
        )}
      </Modal>

      {/* Create Modal */}
      <CreateKBModal
        open={kb.modalVisible}
        form={kb.form}
        searchWeights={kb.searchWeights}
        setSearchWeights={kb.setSearchWeights}
        handleCreate={kb.handleCreate}
        setModalVisible={kb.setModalVisible}
        setLoadedEmbeddingModels={setLoadedEmbeddingModels}
      />

      {/* Edit Modal */}
      <EditKBModal
        editingKB={kb.editingKB}
        open={kb.editModalVisible}
        editForm={kb.editForm}
        editSearchWeights={kb.editSearchWeights}
        setEditSearchWeights={kb.setEditSearchWeights}
        handleUpdate={kb.handleUpdate}
        setEditModalVisible={kb.setEditModalVisible}
      />

      {/* Document List Modal */}
      <Modal
        title={`文档列表: ${c1.docListKB?.name || ''}`}
        open={c1.docListModalVisible}
        onCancel={() => c1.setDocListModalVisible(false)}
        footer={null}
        width={800}
      >
        {c1.docListLoading ? (
          <Text type="secondary">加载中...</Text>
        ) : c1.docList.length === 0 ? (
          <Text type="secondary">暂无文档</Text>
        ) : (
          <List
            size="small"
            dataSource={c1.docList}
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
                      onClick={() => c1.openChunksModal(doc)}
                    >
                      查看分块
                    </Button>
                  ),
                  <Button
                    key="rechunk"
                    size="small"
                    type="link"
                    icon={<AppstoreOutlined />}
                    onClick={() => c1.openRechunkModal(doc)}
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
                      onConfirm={() => c1.handleRetry(doc)}
                    >
                      <Button
                        size="small"
                        type="link"
                        icon={<RedoOutlined />}
                        loading={c1.retryingDocId === doc.id}
                      >
                        重试
                      </Button>
                    </Popconfirm>
                  ),
                  <DeleteDocumentAction
                    loading={c1.deletingDocId === doc.id}
                    onConfirm={() => c1.handleDeleteDocument(doc)}
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
      <ViewChunksModal
        open={c1.chunksModalOpen}
        chunksDoc={c1.chunksDoc}
        chunks={c1.chunks}
        chunksLoading={c1.chunksLoading}
        chunksPage={c1.chunksPage}
        chunksPageSize={c1.chunksPageSize}
        setChunksPage={c1.setChunksPage}
        setChunksPageSize={c1.setChunksPageSize}
        onCancel={() => c1.setChunksModalOpen(false)}
      />

      {/* Re-chunk Modal */}
      <Modal
        title={`重新分块: ${c1.rechunkDoc?.filename || ''}`}
        open={c1.rechunkModalOpen}
        onCancel={() => {
          c1.setRechunkModalOpen(false);
          c1.rechunkForm.resetFields();
        }}
        footer={null}
        width={560}
      >
        <Form
          form={c1.rechunkForm}
          layout="vertical"
          onFinish={c1.handleRechunkSubmit}
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
                loading={c1.rechunkSubmitting}
              >
                提交
              </Button>
              <Button
                onClick={() => {
                  c1.setRechunkModalOpen(false);
                  c1.rechunkForm.resetFields();
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
      <BlockerModal
        state={kb.blockerModal}
        onClose={() =>
          kb.setBlockerModal((prev) => ({ ...prev, visible: false }))
        }
      />
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
