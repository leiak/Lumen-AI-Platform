"use client";

import { useCallback, useRef, useState } from "react";
import { chatApi, type UploadResult } from "@/services/chat";
import type { AttachmentRef } from "@/types/chat";
import { useAppMessage, extractErrorDetail } from "./useAppMessage";

/**
 * M30b-style: 附件上传 + 附件列表 state。
 *
 * 把 page.tsx 里的 fileInputRef + uploading + attachments 状态 + handlePickFile
 * + handleFileSelected 全收编。调用方拿到 { attachments, uploading, fileInputRef,
 * triggerPick, handleFileChange, removeAttachment } —— page 只剩 prop 拼装。
 *
 * `triggerPick` 透传点击到隐藏的 file input,`handleFileChange` 绑在 input 的
 * onChange 上,`removeAttachment` 给 AttachmentChip 用。
 */
export function useChatAttachments() {
  const { message } = useAppMessage();
  const [attachments, setAttachments] = useState<AttachmentRef[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const triggerPick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      // 同一文件连点两次也能触发 onChange —— value 重置
      e.target.value = "";
      if (!file) return;
      setUploading(true);
      try {
        const token = localStorage.getItem("access_token") || "";
        const result: UploadResult = await chatApi.uploadAttachment(file, token);
        setAttachments((prev) => [
          ...prev,
          {
            file_id: result.file_id,
            name: result.name,
            size: result.size,
            mime_type: result.mime_type,
            content_text: result.content_text,
          },
        ]);
        message.success(`已添加附件:${result.name}`);
      } catch (err: unknown) {
        message.error(`上传失败:${extractErrorDetail(err, "未知错误")}`);
      } finally {
        setUploading(false);
      }
    },
    [message]
  );

  const removeAttachment = useCallback((fileId: string) => {
    setAttachments((prev) => prev.filter((x) => x.file_id !== fileId));
  }, []);

  const clearAttachments = useCallback(() => {
    setAttachments([]);
  }, []);

  return {
    attachments,
    uploading,
    fileInputRef,
    triggerPick,
    handleFileChange,
    removeAttachment,
    clearAttachments,
  };
}