"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Form, message } from "antd";
import type { FormInstance } from "antd";

import { knowledgeApi } from "@/services/knowledge";
import type { DocumentResponse, DocumentChunk } from "@/services/knowledge";
import type { KnowledgeBase } from "@/types/api";
import { useNotificationsStore } from "@/store/notifications";

/**
 * M40.1 Phase 4 / 6:文档列表 + 重试/删除/分块/重新分块/通知订阅。
 *
 * 从 page.tsx 搬过来:
 * - 当前 KB 文档列表:documents / loadingDocs / fetchDocuments
 * - 文档数 modal(docList):docListModalVisible / docListKB / docList / docListLoading + openDocList
 * - per-doc loading:retryingDocId / deletingDocId
 * - handlers:handleRetry(doc) / handleDeleteDocument(doc)
 * - 分块 modal:chunksModalOpen / chunksDoc / chunks / chunksLoading / chunksPage / chunksPageSize + openChunksModal + fetchChunks
 * - 重新分块 modal:rechunkModalOpen / rechunkDoc / rechunkSubmitting / rechunkForm + openRechunkModal + handleRechunkSubmit
 * - notification subscription effect(document 通知 → 自动 fetchDocuments)
 * - bridge effect:selectedKB / selectedFolderId 变化 → fetchDocuments
 *
 * 不包含(其他 hook 接管):
 * - searchResults / searchQuery / searchOptions / detailModalVisible / selectedDoc
 *   → useDocumentSearch
 * - selectedDocType / uploadMutation / handleUpload → useDocumentUpload
 *
 * fetchDocuments 闭包问题:hook init 时 args.selectedKB 已有值,但 React 在 props 更新
 * 时会 rerender,callback 内读 ref.current 拿最新 selectedKB / selectedFolderId,
 * 避免 useCallback deps 变化触发重建(其他 hook 会拿 fetchDocuments 引用)。
 */
export interface UseDocumentListArgs {
  /** 当前选中的 KB —— 用来拉 documents 列表、refresh、rechunk 预填 parent 配置 */
  selectedKB: KnowledgeBase | null;
  /** 当前选中的 folder —— documents list 按 folder 过滤 */
  selectedFolderId: number | null;
  /** KB list refresh 回调 —— 删除文档后刷 document_count badge */
  refreshKbList: () => Promise<void>;
  /** 全部 KB 列表(handleRechunk 时按 doc.knowledge_base_id 找 parent KB 拿 chunk_size) */
  allKBs: KnowledgeBase[];
}

export interface UseDocumentListReturn {
  // 当前 KB 文档列表 + 加载状态
  documents: DocumentResponse[];
  loadingDocs: boolean;
  /** 外部触发 fetchDocuments 的接口(KB 切换、文档删除后、breadcrumb 回到根用) */
  refreshDocuments: (kbId?: number, folderId?: number | null) => Promise<void>;

  // docList modal(KB 行「文档数」按钮 → 列出该 KB 全部文档)
  docListModalVisible: boolean;
  setDocListModalVisible: (v: boolean) => void;
  docListKB: KnowledgeBase | null;
  docList: DocumentResponse[];
  docListLoading: boolean;
  openDocList: (kb: KnowledgeBase) => Promise<void>;

  // per-doc loading state —— 给 row 的 spinner 用
  retryingDocId: number | null;
  deletingDocId: number | null;

  // handlers
  handleRetry: (doc: DocumentResponse) => Promise<void>;
  handleDeleteDocument: (doc: DocumentResponse) => Promise<void>;

  // chunks modal
  chunksModalOpen: boolean;
  setChunksModalOpen: (v: boolean) => void;
  chunksDoc: DocumentResponse | null;
  chunks: DocumentChunk[];
  chunksLoading: boolean;
  chunksPage: number;
  setChunksPage: (p: number) => void;
  chunksPageSize: number;
  setChunksPageSize: (n: number) => void;
  /** 打开分块 modal 并拉第一页 */
  openChunksModal: (doc: DocumentResponse) => Promise<void>;

  // rechunk modal
  rechunkModalOpen: boolean;
  setRechunkModalOpen: (v: boolean) => void;
  rechunkDoc: DocumentResponse | null;
  rechunkSubmitting: boolean;
  rechunkForm: FormInstance;
  /** 打开 rechunk modal 并按 parent KB 预填 chunking 配置 */
  openRechunkModal: (doc: DocumentResponse) => void;
  /** rechunk form submit 回调 */
  handleRechunkSubmit: (values: {
    chunking_strategy: string;
    chunk_size: number;
    chunk_overlap: number;
    doc_type?: string;
  }) => Promise<void>;
}

export function useDocumentList(
  args: UseDocumentListArgs
): UseDocumentListReturn {
  const { selectedKB, selectedFolderId, refreshKbList, allKBs } = args;

  // selectedKB / selectedFolderId 通过 ref 同步 —— fetchDocuments useCallback deps
  // 为 [],内部读 ref.current 拿最新值,避免 callback 引用重建。
  const kbIdRef = useRef<number | null>(selectedKB?.id ?? null);
  kbIdRef.current = selectedKB?.id ?? null;
  const folderIdRef = useRef<number | null>(selectedFolderId);
  folderIdRef.current = selectedFolderId;

  // ──────────── 当前 KB 文档列表 ────────────
  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);

  // ──────────── docList modal ────────────
  const [docListModalVisible, setDocListModalVisible] = useState(false);
  const [docListKB, setDocListKB] = useState<KnowledgeBase | null>(null);
  const [docList, setDocList] = useState<DocumentResponse[]>([]);
  const [docListLoading, setDocListLoading] = useState(false);

  // ──────────── per-doc loading ────────────
  const [retryingDocId, setRetryingDocId] = useState<number | null>(null);
  const [deletingDocId, setDeletingDocId] = useState<number | null>(null);

  // ──────────── chunks modal ────────────
  const [chunksModalOpen, setChunksModalOpen] = useState(false);
  const [chunksDoc, setChunksDoc] = useState<DocumentResponse | null>(null);
  const [chunks, setChunks] = useState<DocumentChunk[]>([]);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [chunksPage, setChunksPage] = useState(1);
  const [chunksPageSize, setChunksPageSize] = useState(20);

  // ──────────── rechunk modal ────────────
  const [rechunkModalOpen, setRechunkModalOpen] = useState(false);
  const [rechunkDoc, setRechunkDoc] = useState<DocumentResponse | null>(null);
  const [rechunkSubmitting, setRechunkSubmitting] = useState(false);
  const [rechunkForm] = Form.useForm();

  // ──────────── fetchDocuments ────────────
  const fetchDocuments = useCallback(
    async (kbId?: number, folderId?: number | null) => {
      const id = kbId ?? kbIdRef.current;
      if (id == null) return;
      setLoadingDocs(true);
      try {
        // folderId 优先用入参,fallback 到 ref —— sidebar 切 folder 时入参是新值,
        // ref 也会跟 hook state 同步更新,两个一致即可。
        const fId =
          folderId !== undefined ? folderId : folderIdRef.current;
        const response = await knowledgeApi.getDocuments(
          id,
          fId ?? undefined
        );
        if (response.data.code === 200) {
          setDocuments(response.data.data || []);
        }
      } catch (error) {
        message.error("加载文档列表失败");
      } finally {
        setLoadingDocs(false);
      }
    },
    []
  );

  // ──────────── bridge effect:selectedKB / selectedFolderId 变化 → 自动 fetch ────────────
  useEffect(() => {
    if (selectedKB) {
      fetchDocuments();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKB?.id, selectedFolderId]);

  // ──────────── notification subscription ────────────
  // document 通知 → 当前 KB 时自动 fetchDocuments(通知推送 + refetchUnread backfill)
  useEffect(() => {
    const unsub = useNotificationsStore.subscribe((state, prev) => {
      if (state.items === prev.items) return;
      const newest = state.items[0];
      if (!newest) return;
      if (
        newest.resource_type === "document" &&
        kbIdRef.current !== null &&
        newest.metadata?.kb_id === kbIdRef.current &&
        // 仅响应 length 增长(WS push / refetchUnread / loadMore);
        // markRead / markAllRead / reset 这种只 swap state 的不触发。
        prev.items.length < state.items.length
      ) {
        // M38.2: 通知触发的刷新也得带上 folder 过滤 —— 否则在 folder 视图下
        // 收到的 doc 通知会污染显示成「全部文档」。
        fetchDocuments();
      }
    });
    return () => {
      unsub();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKB?.id, selectedFolderId]);

  // ──────────── openDocList ────────────
  const openDocList = useCallback(async (kb: KnowledgeBase) => {
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
  }, []);

  // ──────────── handleRetry ────────────
  const handleRetry = useCallback(
    async (doc: DocumentResponse) => {
      setRetryingDocId(doc.id);
      try {
        const response = await knowledgeApi.retry(doc.id);
        if (response.data.code === 200) {
          message.success("已重新加入处理队列");
          // 刷新显示该 doc 的列表(docList modal 或 inline 列表)
          if (docListModalVisible && docListKB) {
            await openDocList(docListKB);
          }
          if (kbIdRef.current != null) {
            await fetchDocuments();
          }
        } else {
          message.error(response.data.message || "重试失败");
        }
      } catch (error: any) {
        const detail =
          error?.response?.data?.detail || error?.message || "重试失败";
        message.error(detail);
      } finally {
        setRetryingDocId(null);
      }
    },
    [docListModalVisible, docListKB, openDocList, fetchDocuments]
  );

  // ──────────── handleDeleteDocument ────────────
  const handleDeleteDocument = useCallback(
    async (doc: DocumentResponse) => {
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
          // 刷新显示该 doc 的列表 —— modal 和 inline 列表同一份文档集合
          if (docListModalVisible && docListKB) {
            await openDocList(docListKB);
            if (kbIdRef.current != null && kbIdRef.current !== docListKB.id) {
              await fetchDocuments();
            }
          } else if (kbIdRef.current != null) {
            await fetchDocuments();
          }
          // KB 行的 document_count 是后端算的,手动 refreshKbList() 更新 badge
          await refreshKbList();
        } else {
          message.error(response.data.message || "删除失败");
        }
      } catch (error: any) {
        const detail =
          error?.response?.data?.detail || error?.message || "删除失败";
        message.error(
          typeof detail === "string" ? detail : JSON.stringify(detail)
        );
      } finally {
        setDeletingDocId(null);
      }
    },
    [docListModalVisible, docListKB, fetchDocuments, refreshKbList]
  );

  // ──────────── fetchChunks ────────────
  const fetchChunks = useCallback(
    async (docId: number, page: number, pageSize: number) => {
      setChunksLoading(true);
      try {
        const response = await knowledgeApi.listChunks(docId, page, pageSize);
        if (response.data.code === 200) {
          setChunks(response.data.data || []);
        }
      } catch (error: any) {
        const detail =
          error?.response?.data?.detail ||
          error?.message ||
          "加载分块失败";
        message.error(detail);
        setChunks([]);
      } finally {
        setChunksLoading(false);
      }
    },
    []
  );

  // ──────────── openChunksModal ────────────
  const openChunksModal = useCallback(
    async (doc: DocumentResponse) => {
      setChunksDoc(doc);
      setChunksPage(1);
      setChunksModalOpen(true);
      // 第一页由下方分页 effect 响应(chunksPage=1 / chunksPageSize 初始化后)
      // —— 这里不再手动调 fetchChunks,避免和 effect 竞态。
    },
    []
  );

  // chunks 分页变化 → 自动重新拉(只在 modal open 时)
  useEffect(() => {
    if (!chunksModalOpen || !chunksDoc) return;
    fetchChunks(chunksDoc.id, chunksPage, chunksPageSize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chunksModalOpen, chunksDoc?.id, chunksPage, chunksPageSize]);

  // ──────────── openRechunkModal ────────────
  const openRechunkModal = useCallback(
    (doc: DocumentResponse) => {
      setRechunkDoc(doc);
      // 按 doc 的 knowledge_base_id 找 parent KB,预填 chunking 配置。
      const parentKB = doc.knowledge_base_id
        ? allKBs.find((k) => k.id === doc.knowledge_base_id) || selectedKB
        : null;
      const existingDocType = doc.doc_metadata?.doc_type;
      rechunkForm.setFieldsValue({
        chunking_strategy: "fixed",
        chunk_size: (parentKB as any)?.chunk_size ?? 500,
        chunk_overlap: (parentKB as any)?.chunk_overlap ?? 50,
        doc_type: existingDocType,
      });
      setRechunkModalOpen(true);
    },
    [allKBs, selectedKB, rechunkForm]
  );

  // ──────────── handleRechunkSubmit ────────────
  const handleRechunkSubmit = useCallback(
    async (values: {
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
            await openDocList(docListKB);
          }
          if (kbIdRef.current != null) {
            await fetchDocuments();
          }
        } else {
          message.error(response.data.message || "重新分块失败");
        }
      } catch (error: any) {
        const detail =
          error?.response?.data?.detail ||
          error?.message ||
          "重新分块失败";
        message.error(detail);
      } finally {
        setRechunkSubmitting(false);
      }
    },
    [
      rechunkDoc,
      rechunkForm,
      docListModalVisible,
      docListKB,
      openDocList,
      fetchDocuments,
    ]
  );

  return {
    // documents list
    documents,
    loadingDocs,
    refreshDocuments: fetchDocuments,

    // docList modal
    docListModalVisible,
    setDocListModalVisible,
    docListKB,
    docList,
    docListLoading,
    openDocList,

    // per-doc loading
    retryingDocId,
    deletingDocId,

    // handlers
    handleRetry,
    handleDeleteDocument,

    // chunks modal
    chunksModalOpen,
    setChunksModalOpen,
    chunksDoc,
    chunks,
    chunksLoading,
    chunksPage,
    setChunksPage,
    chunksPageSize,
    setChunksPageSize,
    openChunksModal,

    // rechunk modal
    rechunkModalOpen,
    setRechunkModalOpen,
    rechunkDoc,
    rechunkSubmitting,
    rechunkForm,
    openRechunkModal,
    handleRechunkSubmit,
  };
}