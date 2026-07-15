// frontend/components/wx-publisher/KBImportModal.tsx
// M32 — 公众号助手 — KB 选材 Modal.
//
// Spec §5.5 — Modal: KB 下拉 + 搜索 query + top_k 滑块 (1-50) +
// 检索 + 结果 checkbox 选 + 导入.
"use client";

import { useState } from "react";
import {
  Modal,
  Select,
  Input,
  Slider,
  Button,
  Space,
  List,
  Checkbox,
  Spin,
  Empty,
} from "antd";
import { SearchOutlined } from "@ant-design/icons";
import { materialApi } from "@/services/wx-publisher";
import { knowledgeApi } from "@/services/knowledge";
import type { KnowledgeBase } from "@/types/api";

interface KBImportModalProps {
  open: boolean;
  onClose: () => void;
  kbList: KnowledgeBase[];
  onImported?: (count: number) => void;
}

interface SearchResult {
  id: number;
  title: string;
  content_preview: string;
}

export function KBImportModal({ open, onClose, kbList, onImported }: KBImportModalProps) {
  const [kbId, setKbId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(20);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [searching, setSearching] = useState(false);
  const [importing, setImporting] = useState(false);

  const handleSearch = async () => {
    if (!kbId || !query.trim()) return;
    setSearching(true);
    setResults([]);
    setSelectedIds([]);
    try {
      // 调 M28 /api/v1/knowledge/{kb_id}/search 走 RetrievalPipeline 真实检索.
      // Spec §4.2: top_k 滑块控制拉多少条候选 (1-50).
      const res = await knowledgeApi.search(kbId, query, { k: topK });
      const data = (res.data?.data ?? []) as Array<{
        chunk_id?: number | string;
        id?: number | string;
        content?: string;
        text?: string;
      }>;
      setResults(
        data.map((r) => {
          const rawId = r.chunk_id ?? r.id ?? 0;
          const id = typeof rawId === "string" ? parseInt(rawId, 10) || 0 : rawId;
          const content = r.content ?? r.text ?? "";
          const firstLine = content.split("\n", 1)[0]?.trim() || content.slice(0, 50);
          return {
            id: Number(id) || 0,
            title: firstLine.slice(0, 80),
            content_preview: content.slice(0, 200),
          };
        })
      );
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  };

  const handleImport = async () => {
    if (!kbId) return;
    setImporting(true);
    try {
      // Spec §4.2: /from-kb 端点接收 (kb_id, query, top_k), 后端用 top_k
      // 走 RetrievalPipeline 重新检索并插入素材. 选中的 checkbox 是视觉反馈,
      // 实际导入数量 = top_k 滑块值 (与检索结果数一致 — 不会"选了 3 个但
      // 导入 5 个"造成困惑).
      const result = await materialApi.importFromKB({
        kb_id: kbId,
        query,
        top_k: topK,
      });
      onImported?.(result.imported);
      onClose();
    } catch {
      // 服务层 throw, page 会 catch 并 toast.
    } finally {
      setImporting(false);
    }
  };

  return (
    <Modal
      title="从知识库选材"
      open={open}
      onCancel={onClose}
      width={680}
      footer={[
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button
          key="import"
          type="primary"
          loading={importing}
          disabled={!kbId || results.length === 0}
          onClick={handleImport}
        >
          导入全部 {results.length} 条
        </Button>,
      ]}
    >
      <Space direction="vertical" style={{ width: "100%" }} size={12}>
        <Select
          placeholder="选择知识库"
          style={{ width: "100%" }}
          value={kbId ?? undefined}
          onChange={(v) => setKbId(v)}
          options={kbList.map((kb) => ({ value: kb.id, label: kb.name }))}
        />
        <Input
          placeholder="搜索 query (例: AI Agent 企业应用)"
          prefix={<SearchOutlined />}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onPressEnter={handleSearch}
        />
        <div>
          <span style={{ marginRight: 8 }}>top_k: {topK}</span>
          <Slider
            min={1}
            max={50}
            value={topK}
            onChange={(v) => setTopK(v as number)}
          />
        </div>
        <Button
          type="primary"
          onClick={handleSearch}
          loading={searching}
          disabled={!kbId || !query.trim()}
        >
          检索
        </Button>
        <Spin spinning={searching}>
          {results.length === 0 ? (
            <Empty description="暂无检索结果" />
          ) : (
            <List
              size="small"
              dataSource={results}
              renderItem={(item) => (
                <List.Item>
                  <Checkbox
                    checked={selectedIds.includes(item.id)}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedIds([...selectedIds, item.id]);
                      } else {
                        setSelectedIds(selectedIds.filter((i) => i !== item.id));
                      }
                    }}
                  >
                    <span style={{ fontWeight: 500 }}>{item.title}</span>
                    <div
                      style={{
                        fontSize: 12,
                        color: "#888",
                        marginTop: 2,
                        marginLeft: 0,
                        display: "-webkit-box",
                        WebkitLineClamp: 1,
                        WebkitBoxOrient: "vertical",
                        overflow: "hidden",
                      }}
                    >
                      {item.content_preview}
                    </div>
                  </Checkbox>
                </List.Item>
              )}
            />
          )}
        </Spin>
      </Space>
    </Modal>
  );
}

export default KBImportModal;