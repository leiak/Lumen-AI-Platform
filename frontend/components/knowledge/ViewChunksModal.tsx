"use client";

import { Modal, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import type { DocumentChunk, DocumentResponse } from "@/services/knowledge";

const { Text } = Typography;

interface ViewChunksModalProps {
  open: boolean;
  chunksDoc: DocumentResponse | null;
  chunks: DocumentChunk[];
  chunksLoading: boolean;
  chunksPage: number;
  chunksPageSize: number;
  setChunksPage: (p: number) => void;
  setChunksPageSize: (n: number) => void;
  onCancel: () => void;
}

/**
 * 「分块详情」Modal —— 从 page.tsx 抽出。
 *
 * 由 useDocumentList hook 持有 chunks* state + bridge effect 自动 fetchChunks,
 * page 层只传 props + setChunksPage/setChunksPageSize 触发重新拉取。
 *
 * columns:
 * - # 序号(chunk_index)
 * - 内容(pre,monospace + maxHeight 120 滚动)
 * - 长度(content.length)
 * - 向量ID(末 8 位 + copyable)
 */
export default function ViewChunksModal({
  open,
  chunksDoc,
  chunks,
  chunksLoading,
  chunksPage,
  chunksPageSize,
  setChunksPage,
  setChunksPageSize,
  onCancel,
}: ViewChunksModalProps) {
  const columns: ColumnsType<DocumentChunk> = [
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
  ];

  return (
    <Modal
      title={`分块详情: ${chunksDoc?.filename || ""}`}
      open={open}
      onCancel={onCancel}
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
                // hook 内 bridge effect 监听 chunksPage/PageSize 自动 fetchChunks
              },
            }}
            columns={columns}
          />
        </>
      )}
    </Modal>
  );
}