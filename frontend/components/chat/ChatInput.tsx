"use client";

import { Button, Input } from "antd";
import { SendOutlined } from "@ant-design/icons";
import type { ChangeEvent, RefObject } from "react";
import type { AttachmentRef } from "@/types/chat";
import { FeatureToggles, type FeatureTogglesState } from "./FeatureToggles";
import { AttachmentChip } from "./AttachmentChip";

/**
 * M30b-style: 输入区 — FeatureToggles + 附件 chip + 输入框 + 发送按钮。
 *
 * Props 把所有副作用都透过 callback 上交给 page.tsx:
 * - onChangeToggles / onPickFile / onOpenSkillPicker / onOpenPptConfig
 * - onUpload (file onChange)
 * - onRemoveAttachment / onSend / onChangeInput
 * - fileInputRef 透传 ref 给隐藏的 <input type="file">
 */
export function ChatInput(props: {
  input: string;
  onChangeInput: (v: string) => void;
  toggles: FeatureTogglesState;
  onChangeToggles: (t: FeatureTogglesState) => void;
  onPickFile: () => void;
  onUpload: (e: ChangeEvent<HTMLInputElement>) => void;
  onOpenSkillPicker: () => void;
  onOpenPptConfig: () => void;
  attachments: AttachmentRef[];
  onRemoveAttachment: (fileId: string) => void;
  uploading: boolean;
  streaming: boolean;
  hasConv: boolean;
  onSend: () => void;
  fileInputRef: RefObject<HTMLInputElement>;
}) {
  const {
    input,
    onChangeInput,
    toggles,
    onChangeToggles,
    onPickFile,
    onUpload,
    onOpenSkillPicker,
    onOpenPptConfig,
    attachments,
    onRemoveAttachment,
    uploading,
    streaming,
    hasConv,
    onSend,
    fileInputRef,
  } = props;

  return (
    <div
      style={{
        padding: 16,
        borderTop: "1px solid #f0f0f0",
        background: "#fff",
      }}
    >
      <input
        ref={fileInputRef}
        type="file"
        style={{ display: "none" }}
        onChange={onUpload}
        accept=".txt,.md,.pdf,.docx,.pptx,.xlsx"
      />
      <FeatureToggles
        value={toggles}
        onChange={onChangeToggles}
        onPickFile={onPickFile}
        onOpenSkillPicker={onOpenSkillPicker}
        onOpenPptConfig={onOpenPptConfig}
        hasAttachments={attachments.length > 0}
        disabled={!hasConv || streaming || uploading}
      />
      {attachments.length > 0 && (
        <div style={{ marginBottom: 8, display: "flex", flexWrap: "wrap" }}>
          {attachments.map((a) => (
            <AttachmentChip
              key={a.file_id}
              attachment={a}
              onRemove={() => onRemoveAttachment(a.file_id)}
            />
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 8 }}>
        <Input
          value={input}
          onChange={(e) => onChangeInput(e.target.value)}
          onPressEnter={onSend}
          placeholder={
            uploading
              ? "上传中..."
              : hasConv
              ? "输入消息..."
              : "请先选择对话"
          }
          disabled={!hasConv || streaming || uploading}
          size="large"
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={onSend}
          loading={streaming}
          disabled={!hasConv || uploading}
          size="large"
        />
      </div>
    </div>
  );
}