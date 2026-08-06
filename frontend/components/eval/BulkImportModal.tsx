"use client";

// frontend/components/eval/BulkImportModal.tsx
// M37.1 — Bulk import items into an eval dataset (shared by list page
// batch-add shortcut + detail page toolbar).
//
// 两种数据来源:
//   1. 文本框:用户直接粘贴 JSON 数组 (Array<{query, expected_doc_ids?, ...}>)
//   2. 文件上传:.json 文件读取后塞进文本框(用户仍可手动改)
//
// 调用流程:
//   - 用户输入 → 本地预览(parse 一次 + antd Alert 标行数)
//   - 点「导入」→ bulkImportItems() → 后端 per-row Pydantic 校验
//   - 后端 200 OK + partial_errors → 这里展示「成功 N 行 / 失败 M 行」
//     + 错误行(row_index / error 摘要)表格
//
// 注意:不在前端做 Pydantic Literal 校验(category / difficulty 必须落在合法枚举),
// 那是后端 partial_errors 的职责。前端只做 JSON parse,把脏数据交给后端分类。

import { useState, useEffect } from "react";
import {
  Modal,
  Button,
  Input,
  Upload,
  Alert,
  Table,
  Tag,
  Space,
  App,
} from "antd";
import { InboxOutlined, FileTextOutlined } from "@ant-design/icons";
import type { UploadProps } from "antd";
import { bulkImportItems } from "@/services/eval_dataset";
import type {
  EvalDatasetItemBulkImportError,
  EvalDatasetItemBulkImportRow,
  EvalDatasetItemBulkImportResponse,
} from "@/types/eval_dataset";

const { TextArea } = Input;
const { Dragger } = Upload;

interface BulkImportModalProps {
  open: boolean;
  datasetId: number;
  onCancel: () => void;
  onSuccess: (resp: EvalDatasetItemBulkImportResponse) => void;
}

interface PreviewState {
  ok: boolean;
  rows: EvalDatasetItemBulkImportRow[];
  error?: string;
}

const PLACEHOLDER = `[
  {
    "query": "如何申请退货?",
    "expected_doc_ids": [12, 18],
    "expected_answer": "7 天内联系客服...",
    "answer_keywords": ["退货", "7 天"],
    "category": "factual",
    "difficulty": "easy"
  },
  {
    "query": "为什么我的订单状态没更新?",
    "expected_doc_ids": [33],
    "category": "reasoning",
    "difficulty": "medium"
  }
]`;

export default function BulkImportModal({
  open,
  datasetId,
  onCancel,
  onSuccess,
}: BulkImportModalProps) {
  const { message } = App.useApp();
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<EvalDatasetItemBulkImportResponse | null>(
    null,
  );

  // 打开 modal 时重置
  useEffect(() => {
    if (open) {
      setText("");
      setPreview(null);
      setResult(null);
    }
  }, [open]);

  // 文本变化时本地 parse 一次(仅检查「是不是合法 JSON 数组」,不校验字段)
  const handleTextChange = (val: string) => {
    setText(val);
    setResult(null);
    if (!val.trim()) {
      setPreview(null);
      return;
    }
    try {
      const parsed = JSON.parse(val);
      if (!Array.isArray(parsed)) {
        setPreview({ ok: false, rows: [], error: "根节点必须是 JSON 数组" });
        return;
      }
      if (parsed.length === 0) {
        setPreview({ ok: false, rows: [], error: "数组不能为空" });
        return;
      }
      setPreview({ ok: true, rows: parsed as EvalDatasetItemBulkImportRow[] });
    } catch (e) {
      setPreview({
        ok: false,
        rows: [],
        error: `JSON 解析失败:${(e as Error).message}`,
      });
    }
  };

  // 文件上传:读 → 塞进文本框
  const uploadProps: UploadProps = {
    accept: ".json",
    multiple: false,
    showUploadList: false,
    beforeUpload: (file) => {
      const reader = new FileReader();
      reader.onload = () => {
        handleTextChange(String(reader.result ?? ""));
        message.success(`已加载 ${file.name}`);
      };
      reader.onerror = () => message.error("文件读取失败");
      reader.readAsText(file);
      return false; // 阻止 antd 自动上传
    },
  };

  const handleImport = async () => {
    if (!preview?.ok) return;
    setSubmitting(true);
    try {
      const resp = await bulkImportItems(datasetId, { rows: preview.rows });
      setResult(resp);
      onSuccess(resp);
      if (resp.failed_count === 0) {
        // 全部成功 → 自动关闭 modal
        message.success(`成功导入 ${resp.imported_count} 条`);
        onCancel();
      } else if (resp.imported_count > 0) {
        // 部分成功 → 留着 modal 让用户看错误行
        message.warning(
          `已导入 ${resp.imported_count} 条,${resp.failed_count} 条失败(见下方表格)`,
        );
      } else {
        message.error(`全部 ${resp.failed_count} 条失败`);
      }
    } catch (e) {
      message.error(`导入失败:${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const errorColumns = [
    { title: "行号", dataIndex: "row_index", width: 80 },
    { title: "错误", dataIndex: "error", ellipsis: true },
  ];

  return (
    <Modal
      title={`批量导入 items — dataset #${datasetId}`}
      open={open}
      onCancel={onCancel}
      width={720}
      footer={[
        <Button key="cancel" onClick={onCancel}>
          关闭
        </Button>,
        <Button
          key="submit"
          type="primary"
          loading={submitting}
          disabled={!preview?.ok}
          onClick={handleImport}
        >
          导入 {preview?.ok ? `(${preview.rows.length} 条)` : ""}
        </Button>,
      ]}
      destroyOnClose
    >
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <Dragger {...uploadProps}>
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽 .json 文件到此区域</p>
          <p className="ant-upload-hint">
            文件内容必须是 JSON 数组,每项至少包含 query 字段
          </p>
        </Dragger>

        <div>
          <div style={{ marginBottom: 4, color: "#666" }}>
            <FileTextOutlined /> 或直接粘贴 JSON:
          </div>
          <TextArea
            value={text}
            onChange={(e) => handleTextChange(e.target.value)}
            placeholder={PLACEHOLDER}
            autoSize={{ minRows: 6, maxRows: 14 }}
            style={{ fontFamily: "monospace", fontSize: 12 }}
          />
        </div>

        {preview && !preview.ok && (
          <Alert
            type="error"
            showIcon
            message={preview.error ?? "JSON 不合法"}
          />
        )}
        {preview?.ok && (
          <Alert
            type="info"
            showIcon
            message={`本地预览:共 ${preview.rows.length} 条。点击「导入」提交至后端,逐行 Pydantic 校验(category/difficulty 必须落在合法枚举)。`}
          />
        )}

        {result && result.failed_count > 0 && (
          <Alert
            type="warning"
            showIcon
            message={
              <Space>
                <span>导入完成:</span>
                <Tag color="green">成功 {result.imported_count}</Tag>
                <Tag color="red">失败 {result.failed_count}</Tag>
              </Space>
            }
          />
        )}
        {result && result.failed_count > 0 && (
          <Table<EvalDatasetItemBulkImportError>
            rowKey={(r) => `${r.row_index}-${r.error}`}
            size="small"
            pagination={false}
            dataSource={result.partial_errors}
            columns={errorColumns}
          />
        )}
      </Space>
    </Modal>
  );
}