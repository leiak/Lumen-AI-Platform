// frontend/components/wx-publisher/AIRewriteModal.tsx
// M32 — 公众号助手 — AI 改写 / 扩写 Modal (Diff 对比).
//
// Spec §5.3 — Modal: instruction 表单 + 调 API + 弹 Diff 对比 (左 diff 右 new).
// jsdom 无原生 diff lib, 用纯文本行级对比 + 简单 highlight.
"use client";

import { useState } from "react";
import {
  Modal,
  Form,
  Input,
  Button,
  Space,
  Spin,
  Alert,
  Typography,
} from "antd";
import type { WxDraftSectionResponse, AIActionType } from "@/types/wx-publisher";

const { TextArea } = Input;
const { Paragraph } = Typography;

// Re-export the shared type from types/wx-publisher so callers and
// components stay in sync. The single source of truth lives in
// types/wx-publisher.ts.
export type { AIActionType } from "@/types/wx-publisher";

interface AIRewriteModalProps {
  open: boolean;
  action: AIActionType;
  section: WxDraftSectionResponse | null;
  /** 调用 API 后返的新 markdown, 不自动覆写, 用户点 [应用] 才生效. */
  newContent?: string | null;
  loading?: boolean;
  onCancel: () => void;
  onSubmit: (instruction: string, expansionRatio?: number) => void;
  onApply?: (newContent: string) => void;
}

const ACTION_LABELS: Record<AIActionType, { title: string; submit: string }> = {
  rewrite: { title: "AI 改写", submit: "确认改写" },
  expand: { title: "AI 扩写", submit: "确认扩写" },
  title: { title: "AI 标题", submit: "确认生成" },
  outline: { title: "AI 大纲", submit: "确认生成" },
  render: { title: "排版", submit: "确认排版" },
};

/** 简单行级 diff — 只标记增/删, 不做 LCS(避免引入 diff lib).
 *  返回 [{ type: 'unchanged' | 'added' | 'removed', text }]. */
function lineDiff(before: string, after: string) {
  const a = before.split("\n");
  const b = after.split("\n");
  const out: Array<{ type: "unchanged" | "added" | "removed"; text: string }> = [];
  // 简化策略: 保留 unchanged 相同行 + 标记 added/removed.
  const bSet = new Set(b);
  const aSet = new Set(a);
  for (const line of a) {
    if (bSet.has(line)) {
      out.push({ type: "unchanged", text: line });
    } else {
      out.push({ type: "removed", text: line });
    }
  }
  for (const line of b) {
    if (!aSet.has(line)) {
      out.push({ type: "added", text: line });
    }
  }
  return out;
}

const DIFF_COLORS: Record<string, { bg: string; fg: string }> = {
  unchanged: { bg: "transparent", fg: "#555" },
  added: { bg: "#f6ffed", fg: "#389e0d" },
  removed: { bg: "#fff1f0", fg: "#cf1322" },
};

export function AIRewriteModal({
  open,
  action,
  section,
  newContent,
  loading,
  onCancel,
  onSubmit,
  onApply,
}: AIRewriteModalProps) {
  const [form] = Form.useForm();
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async () => {
    const values = await form.validateFields();
    setSubmitted(true);
    onSubmit(values.instruction, values.expansion_ratio);
  };

  const handleClose = () => {
    setSubmitted(false);
    form.resetFields();
    onCancel();
  };

  const labels = ACTION_LABELS[action];
  const diff = submitted && newContent && section
    ? lineDiff(section.content_markdown, newContent)
    : [];

  return (
    <Modal
      title={labels.title}
      open={open}
      onCancel={handleClose}
      width={760}
      footer={
        submitted && newContent
          ? [
              <Button key="cancel" onClick={handleClose}>
                取消
              </Button>,
              <Button
                key="apply"
                type="primary"
                onClick={() => {
                  onApply?.(newContent);
                  handleClose();
                }}
              >
                应用到章节
              </Button>,
            ]
          : [
              <Button key="cancel" onClick={handleClose}>
                取消
              </Button>,
              <Button key="submit" type="primary" loading={loading} onClick={handleSubmit}>
                {labels.submit}
              </Button>,
            ]
      }
    >
      {!submitted && (
        <Form form={form} layout="vertical" initialValues={{ expansion_ratio: 1.5 }}>
          <Form.Item
            name="instruction"
            label={action === "rewrite" ? "改写指令" : "扩写方向"}
            rules={[{ required: true, message: "请输入指令" }]}
          >
            <TextArea
              rows={3}
              placeholder={
                action === "rewrite"
                  ? "例: 改得更口语化, 加 1 个案例"
                  : "例: 增加实施步骤的细节"
              }
            />
          </Form.Item>
          {action === "expand" && (
            <Form.Item name="expansion_ratio" label="扩写比例 (1.2 - 3.0)">
              <Input type="number" min={1.2} max={3.0} step={0.1} />
            </Form.Item>
          )}
        </Form>
      )}

      {submitted && loading && (
        <div style={{ textAlign: "center", padding: 32 }}>
          <Spin tip="AI 创作中..." />
        </div>
      )}

      {submitted && newContent && !loading && (
        <Space direction="vertical" style={{ width: "100%" }} size={12}>
          <Alert
            type="info"
            showIcon
            message="AI 生成完成, 请对比左右两侧后选择是否应用."
          />
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 12,
            }}
          >
            <div>
              <Paragraph strong>原内容</Paragraph>
              <pre
                style={{
                  background: "#fafafa",
                  padding: 8,
                  borderRadius: 4,
                  fontSize: 12,
                  maxHeight: 320,
                  overflow: "auto",
                  whiteSpace: "pre-wrap",
                }}
              >
                {section?.content_markdown}
              </pre>
            </div>
            <div>
              <Paragraph strong>新内容 (Diff)</Paragraph>
              <pre
                style={{
                  background: "#fafafa",
                  padding: 8,
                  borderRadius: 4,
                  fontSize: 12,
                  maxHeight: 320,
                  overflow: "auto",
                  whiteSpace: "pre-wrap",
                }}
              >
                {diff.map((d, i) => (
                  <div
                    key={i}
                    style={{
                      background: DIFF_COLORS[d.type].bg,
                      color: DIFF_COLORS[d.type].fg,
                      padding: "0 4px",
                    }}
                  >
                    {d.type === "added" ? "+ " : d.type === "removed" ? "- " : "  "}
                    {d.text}
                  </div>
                ))}
              </pre>
            </div>
          </div>
        </Space>
      )}
    </Modal>
  );
}

export default AIRewriteModal;