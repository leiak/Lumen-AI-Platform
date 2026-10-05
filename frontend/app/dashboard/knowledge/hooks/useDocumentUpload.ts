"use client";

import { useCallback, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { message } from "antd";

import { knowledgeApi } from "@/services/knowledge";

/**
 * M40.1 Phase 3 / 6:文档上传 mutation + doc type picker。
 *
 * 从 page.tsx 搬过来:
 * - selectedDocType / setSelectedDocType(上传时的文档类型,parser type picker)
 * - uploadMutation(useMutation + onMutate message.loading + onSuccess message + onError)
 * - handleUpload(给 AntD Upload.beforeUpload 用的 wrapper)
 *
 * page 层 args.onUploadSuccess 封装 upload 后副作用:
 * - 刷 KB list 文档数 badge(kb.refreshKbList)
 * - 若 KB 已选中,刷文档列表(queryClient.invalidateQueries + fetchDocuments)
 *
 * 不包含(Phase 4 useDocumentList 接管):
 * - documents / loadingDocs / fetchDocuments
 */
export interface UseDocumentUploadArgs {
  /** 当前选中的 folder(null = KB 根目录),上传文件落到这个 folder。 */
  currentFolderId: number | null;
  /** upload 完成后通知 page 刷 KB list badge + 文档列表。 */
  onUploadSuccess?: (kbId: number) => void;
}

export interface UseDocumentUploadReturn {
  // doc type picker —— 给 <Select value={selectedDocType} onChange={setSelectedDocType} />
  selectedDocType: string;
  setSelectedDocType: (v: string) => void;

  // mutation —— 给 inline KB row / 当前 KB documents tab 的 <Upload> 用
  // 用来判断当前 row 是否正在上传(uploadMutation.isPending + variables?.kbId === row.id)
  uploadMutation: ReturnType<
    typeof useMutation<any, any, { kbId: number; file: File; docType?: string; folderId?: number }>
  >;

  // 给 AntD Upload.beforeUpload 用 —— 返回 false 阻止默认上传
  handleUpload: (kbId: number, file: File) => boolean;
}

export function useDocumentUpload(
  args: UseDocumentUploadArgs
): UseDocumentUploadReturn {
  const { currentFolderId, onUploadSuccess } = args;

  const [selectedDocType, setSelectedDocType] = useState<string>("");

  const uploadMutation = useMutation({
    mutationFn: ({
      kbId,
      file,
      docType,
      folderId,
    }: {
      kbId: number;
      file: File;
      docType?: string;
      folderId?: number;
    }) => knowledgeApi.upload(kbId, file, docType, folderId),
    onMutate: () => {
      message.loading("上传中...", 0);
    },
    onSuccess: (response, variables) => {
      message.destroy();
      if (response.data.code === 200) {
        message.success("上传成功");
      } else {
        message.error(response.data.message || "上传失败");
      }
      onUploadSuccess?.(variables.kbId);
    },
    onError: (error: any) => {
      message.destroy();
      if (error.response?.status === 413) {
        message.error("文件太大");
      } else {
        message.error("上传失败");
      }
    },
  });

  const handleUpload = useCallback(
    (kbId: number, file: File) => {
      uploadMutation.mutate({
        kbId,
        file,
        docType: selectedDocType,
        folderId: currentFolderId ?? undefined,
      });
      return false; // prevent default upload behavior
    },
    [uploadMutation, selectedDocType, currentFolderId]
  );

  return {
    selectedDocType,
    setSelectedDocType,
    uploadMutation,
    handleUpload,
  };
}