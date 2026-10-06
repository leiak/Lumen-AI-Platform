"use client";

import { useCallback, useState } from "react";
import { message } from "antd";

import { knowledgeApi } from "@/services/knowledge";
import type { KnowledgeBase } from "@/types/api";

/**
 * 搜索结果 shape —— 后端返回的 chunk + 距离得分 + 元数据。
 * page 层 + DetailModal + 列表渲染都引用,搬到 hook 内并 export 共享。
 */
export interface SearchResult {
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

/**
 * M40.1 Phase 5 / 6:文档搜索 + 高级选项 + detail modal。
 *
 * 从 page.tsx 搬过来:
 * - searchQuery / setSearchQuery(搜索框输入)
 * - searchOptions / setSearchOptions(k / alpha / rerank / rerankTopN / fieldWeights)
 * - searching / searchResults(搜索执行状态 + 结果)
 * - selectedDoc / detailModalVisible / setDetailModalVisible(点结果项 → 详情 modal)
 * - handleSearch(发起 search 调用)+ showDetail(打开详情 modal)
 *
 * 不包含(其他 hook 接管):
 * - searchResults 跟 documents 列表独立 —— search 一次的结果只显示在搜索结果区,
 *   跟当前 KB 文档列表不混淆。
 * - documents / loadingDocs / fetchDocuments → useDocumentList
 * - selectedKB 由 page 层通过 args 传入;KB 切换后 onKbChangeCleanup 会清
 *   searchResults / searchQuery(在 useKnowledgeList 里调)。
 */
export interface UseDocumentSearchArgs {
  /** 当前选中的 KB —— 没选时 search 提示「请选择知识库」 */
  selectedKB: KnowledgeBase | null;
}

export interface UseDocumentSearchReturn {
  // query input
  searchQuery: string;
  setSearchQuery: (v: string) => void;

  // advanced options(k / alpha / rerank / rerankTopN / fieldWeights)
  searchOptions: {
    k: number;
    alpha: number;
    rerank: boolean;
    rerankTopN: number;
    fieldWeights: string;
  };
  setSearchOptions: (
    v:
      | {
          k: number;
          alpha: number;
          rerank: boolean;
          rerankTopN: number;
          fieldWeights: string;
        }
      | ((prev: {
          k: number;
          alpha: number;
          rerank: boolean;
          rerankTopN: number;
          fieldWeights: string;
        }) => {
          k: number;
          alpha: number;
          rerank: boolean;
          rerankTopN: number;
          fieldWeights: string;
        })
  ) => void;

  // search execution
  searching: boolean;
  searchResults: SearchResult[];

  // handlers
  handleSearch: () => Promise<void>;
  showDetail: (result: SearchResult) => void;

  // detail modal state
  detailModalVisible: boolean;
  setDetailModalVisible: (v: boolean) => void;
  selectedDoc: SearchResult | null;
}

const SEARCH_OPTIONS_DEFAULTS = {
  k: 5,
  alpha: 0.5,
  rerank: true,
  rerankTopN: 10,
  fieldWeights: "",
};

export function useDocumentSearch(
  args: UseDocumentSearchArgs
): UseDocumentSearchReturn {
  const { selectedKB } = args;

  // query input
  const [searchQuery, setSearchQuery] = useState("");

  // advanced options
  const [searchOptions, setSearchOptions] = useState(SEARCH_OPTIONS_DEFAULTS);

  // search execution
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);

  // detail modal state
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState<SearchResult | null>(null);

  // ──────────── handleSearch ────────────
  const handleSearch = useCallback(async () => {
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
      const response = await knowledgeApi.search(
        selectedKB.id,
        searchQuery,
        options
      );
      if (response.data.code === 200) {
        const results = response.data.data || [];
        setSearchResults(results);
        if (results.length === 0) {
          message.info("未找到相关结果");
        }
      }
    } catch (error) {
      message.error("搜索失败");
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  }, [selectedKB, searchQuery, searchOptions]);

  // ──────────── showDetail ────────────
  const showDetail = useCallback((result: SearchResult) => {
    setSelectedDoc(result);
    setDetailModalVisible(true);
  }, []);

  return {
    searchQuery,
    setSearchQuery,
    searchOptions,
    setSearchOptions,
    searching,
    searchResults,
    handleSearch,
    showDetail,
    detailModalVisible,
    setDetailModalVisible,
    selectedDoc,
  };
}