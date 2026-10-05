"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Form, message } from "antd";
import type { FormInstance } from "antd";

import { knowledgeApi } from "@/services/knowledge";
import type { KnowledgeBase as SBKKnowledgeBase } from "@/types/api";
import type { ModelConfig } from "@/services/models";

/**
 * M40.1 Phase 2 / 6: KB list 状态 + CRUD + blocker modal。
 *
 * 从 page.tsx 搬过来:
 * - data / loading / page / pageSize / total(KB 列表 + 翻页)
 * - selectedKB(选中状态从 page 层搬进 hook,通过 args.onKbChange 由 useWorkspaceTree 触发)
 * - modalVisible / form(创建 modal)
 * - searchWeights(创建 modal 的搜索权重 slider)
 * - loadedEmbeddingModels(useQuery 拉 embedding 模型列表)
 * - editingKB / editModalVisible / editForm(编辑 modal)
 * - editSearchWeights(编辑 modal 的搜索权重 slider)
 * - blockerModal(M28 422 引用计数拦截 — 详情 modal)
 * - handleCreate / handleDelete / handleEdit / handleUpdate / handleSelectKB / fetchData
 *
 * 不包含(useDocumentList / useDocumentUpload 之后接管):
 * - documents / fetchDocuments / selectedDocType / uploadMutation / handleUpload
 * - handleViewDocs / handleRetry / handleDeleteDocument(都依赖 documents)
 * - docList* state(docList modal 是 useDocumentList 的)
 * - searchResults / searchQuery / searchOptions(用 useDocumentSearch 接管)
 *
 * Phase 2 不搬 columns:columns 在 700~1170 之间,引用 handleViewDocs / handleSelectKB / handleUpload /
 * selectedKB / uploadMutation 等多个 hook,等 Phase 3/4 完成后(201 假设),才把 columns 移进 hook。
 */
export interface UseKnowledgeListArgs {
  /** workspace 筛选 —— 由 useWorkspaceTree 提供,null = 未分组 */
  selectedWorkspaceId: number | null;
  /** fetchDocuments 的 callback —— KB 切换后由 hook 主动触发,page 层传 */
  onKbSelectFetchDocs?: (kbId: number) => void;
  /** KB 切换时清 search / 清文档 list / 清 folder 选择 —— 由 page 层 inline 函数封装 */
  onKbChangeCleanup?: (kb: SBKKnowledgeBase | null) => void;
  /** EmbeddingModelSelect.onLoaded 缓存 —— page 层维护,hook 读取 */
  loadedEmbeddingModels: ModelConfig[];
}

export interface UseKnowledgeListReturn {
  // KB list 列表 + 翻页
  data: SBKKnowledgeBase[];
  loading: boolean;
  page: number;
  setPage: (p: number) => void;
  pageSize: number;
  setPageSize: (n: number) => void;
  total: number;
  refreshKbList: () => Promise<void>;

  // 创建 modal
  modalVisible: boolean;
  setModalVisible: (v: boolean) => void;
  form: FormInstance;

  // 创建 modal 的 search weights slider
  searchWeights: { title: number; important_kw: number; question_kw: number; text: number };
  setSearchWeights: (
    v: { title: number; important_kw: number; question_kw: number; text: number }
  ) => void;

  // embedding 模型列表(form auto-default 用)
  loadedEmbeddingModels: ModelConfig[];

  // 当前选中的 KB(hook 持有)
  selectedKB: SBKKnowledgeBase | null;
  setSelectedKB: (kb: SBKKnowledgeBase | null) => void;

  // 编辑 modal
  editingKB: SBKKnowledgeBase | null;
  editModalVisible: boolean;
  setEditModalVisible: (v: boolean) => void;
  editForm: FormInstance;
  editSearchWeights: {
    title: number;
    important_kw: number;
    question_kw: number;
    text: number;
  };
  setEditSearchWeights: (
    v: { title: number; important_kw: number; question_kw: number; text: number }
  ) => void;

  // M28: blocker modal(422 引用计数拦截)
  blockerModal: {
    visible: boolean;
    message: string;
    agents: any[];
    documents: any[];
    truncated: boolean;
  };
  setBlockerModal: React.Dispatch<
    React.SetStateAction<{
      visible: boolean;
      message: string;
      agents: any[];
      documents: any[];
      truncated: boolean;
    }>
  >;

  // handlers
  handleSelectKB: (kb: SBKKnowledgeBase | null) => void;
  handleCreate: (values: any) => Promise<void>;
  handleDelete: (id: number) => Promise<void>;
  handleEdit: (kb: SBKKnowledgeBase) => void;
  handleUpdate: (values: any) => Promise<void>;
}

const SEARCH_WEIGHTS_DEFAULTS = {
  title: 10.0,
  important_kw: 30.0,
  question_kw: 20.0,
  text: 2.0,
};

export function useKnowledgeList(
  args: UseKnowledgeListArgs
): UseKnowledgeListReturn {
  const {
    selectedWorkspaceId,
    onKbSelectFetchDocs,
    onKbChangeCleanup,
    loadedEmbeddingModels,
  } = args;

  // selectedWorkspaceId 通过 ref 同步 —— kb hook 在 ws 之前 init,args.selectedWorkspaceId
  // 第一次为 null(handler closure 拿到 init 时的 null 就丢新值)。ref 同步方式让
  // handler 内读最新 ws.selectedWorkspaceId。
  const wsIdRef = useRef<number | null>(selectedWorkspaceId);
  wsIdRef.current = selectedWorkspaceId;

  // ──────────── KB list + 翻页 ────────────
  const [data, setData] = useState<SBKKnowledgeBase[]>([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [total, setTotal] = useState(0);

  // ──────────── 创建 modal ────────────
  const [modalVisible, setModalVisible] = useState(false);
  const [form] = Form.useForm();
  const [searchWeights, setSearchWeights] = useState(SEARCH_WEIGHTS_DEFAULTS);

  // ──────────── 编辑 modal ────────────
  const [editingKB, setEditingKB] = useState<SBKKnowledgeBase | null>(null);
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [editForm] = Form.useForm();
  const [editSearchWeights, setEditSearchWeights] = useState(
    SEARCH_WEIGHTS_DEFAULTS
  );

  // ──────────── 当前选中 KB(从 page 层搬过来)────────────
  const [selectedKB, setSelectedKB] = useState<SBKKnowledgeBase | null>(null);

  // ──────────── Blocker modal(M28 422 拦截)────────────
  const [blockerModal, setBlockerModal] = useState<{
    visible: boolean;
    message: string;
    agents: any[];
    documents: any[];
    truncated: boolean;
  }>({
    visible: false,
    message: "",
    agents: [],
    documents: [],
    truncated: false,
  });

  // ──────────── embedding 模型列表 ────────────
  // 不在 hook 里 fetch,避免跟 EmbeddingModelSelect 组件内部 fetch 抢请求。
  // 由 page 层通过 args.loadedEmbeddingModels 传入(EmbeddingModelSelect.onLoaded)。

  // ──────────── fetchData ────────────
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const response = await knowledgeApi.list(
        page,
        pageSize,
        wsIdRef.current ?? undefined
      );
      if (response.data.code === 200) {
        setData(response.data.data || []);
        setTotal(response.data.total || 0);
      }
    } catch (error) {
      message.error("获取知识库列表失败");
    } finally {
      setLoading(false);
    }
  }, [page, pageSize]);

  // workspace 切换或翻页时拉 KB list
  useEffect(() => {
    fetchData();
  }, [fetchData, selectedWorkspaceId]);

  // ──────────── auto-default embedding(form 打开时)────────────
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

  // ──────────── handleSelectKB ────────────
  const handleSelectKB = useCallback(
    (kb: SBKKnowledgeBase | null) => {
      setSelectedKB(kb);
      // 通知 page 层清 search / 清文档 / 清 folder
      onKbChangeCleanup?.(kb);
      if (kb) {
        onKbSelectFetchDocs?.(kb.id);
      }
    },
    [onKbChangeCleanup, onKbSelectFetchDocs]
  );

  // ──────────── handleCreate ────────────
  const handleCreate = useCallback(
    async (values: any) => {
      try {
        const payload = {
          ...values,
          search_weights: searchWeights,
        };
        // 通过 ref 读最新 selectedWorkspaceId —— kb hook 在 ws 之前 init 时,
        // args.selectedWorkspaceId 是 null,handler closure 拿不到后续 ws 值。
        const wsId = wsIdRef.current;
        const response = await knowledgeApi.create(
          payload,
          wsId != null && wsId > 0 ? wsId : undefined
        );
        if (response.data.code === 200) {
          message.success("创建成功");
          setModalVisible(false);
          form.resetFields();
          await fetchData();
        }
      } catch (error) {
        message.error("创建失败");
      }
    },
    [searchWeights, form, fetchData]
  );

  // ──────────── handleDelete ────────────
  const handleDelete = useCallback(
    async (id: number) => {
      try {
        await knowledgeApi.delete(id);
        message.success("删除成功");
        if (selectedKB?.id === id) {
          handleSelectKB(null);
        }
        await fetchData();
      } catch (error: any) {
        // M28: 422 = 引用计数拦截 → blocker modal
        const status = error?.response?.status;
        const detail = error?.response?.data?.detail;
        if (status === 422 && detail && typeof detail === "object") {
          setBlockerModal({
            visible: true,
            message:
              typeof detail.message === "string"
                ? detail.message
                : "该知识库仍被其他资源引用,无法删除。",
            agents: Array.isArray(detail.blocking_agents)
              ? detail.blocking_agents
              : [],
            documents: Array.isArray(detail.blocking_documents)
              ? detail.blocking_documents
              : [],
            truncated: detail.truncated === true,
          });
          return;
        }
        // 兜底:detail 是 string
        const fbMsg = typeof detail === "string" ? detail : "删除失败";
        message.error(fbMsg);
      }
    },
    [selectedKB, handleSelectKB, fetchData]
  );

  // ──────────── handleEdit ────────────
  const handleEdit = useCallback(
    (kb: SBKKnowledgeBase) => {
      setEditingKB(kb);
      editForm.setFieldsValue({
        name: kb.name,
        description: kb.description,
        embedding_model_config_id: kb.embedding_model_config_id ?? undefined,
        default_parser: kb.default_parser || "general",
        chunk_size: kb.chunk_size || 500,
        chunk_overlap: kb.chunk_overlap || 50,
      });
      if (kb.search_weights) {
        setEditSearchWeights({
          title: kb.search_weights.title || SEARCH_WEIGHTS_DEFAULTS.title,
          important_kw:
            kb.search_weights.important_kw ||
            SEARCH_WEIGHTS_DEFAULTS.important_kw,
          question_kw:
            kb.search_weights.question_kw || SEARCH_WEIGHTS_DEFAULTS.question_kw,
          text: kb.search_weights.text || SEARCH_WEIGHTS_DEFAULTS.text,
        });
      }
      setEditModalVisible(true);
    },
    [editForm]
  );

  // ──────────── handleUpdate ────────────
  const handleUpdate = useCallback(
    async (values: any) => {
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
          await fetchData();
          // 编辑后刷新 selectedKB 缓存
          if (selectedKB?.id === editingKB.id && response.data.data) {
            setSelectedKB({ ...selectedKB, ...response.data.data });
          }
        }
      } catch (error) {
        message.error("更新失败");
      }
    },
    [editingKB, editSearchWeights, editForm, fetchData, selectedKB]
  );

  return {
    data,
    loading,
    page,
    setPage,
    pageSize,
    setPageSize,
    total,
    refreshKbList: fetchData,

    modalVisible,
    setModalVisible,
    form,

    searchWeights,
    setSearchWeights,

    loadedEmbeddingModels,

    selectedKB,
    setSelectedKB,

    editingKB,
    editModalVisible,
    setEditModalVisible,
    editForm,
    editSearchWeights,
    setEditSearchWeights,

    blockerModal,
    setBlockerModal,

    handleSelectKB,
    handleCreate,
    handleDelete,
    handleEdit,
    handleUpdate,
  };
}