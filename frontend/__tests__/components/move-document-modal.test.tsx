// M38.2: MoveDocumentModal — 当前 folder 默认值 + 目标 folder 选择 + 提交 payload。
//
// 覆盖:
// 1. 标题里显示 documentId
// 2. currentFolderId=null 时默认选 "KB 根目录";currentFolderId=具体值时也允许选中
// 3. 点「移动」 → onSubmit 收到 { target_folder_id: null | number }

import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ConfigProvider, App } from "antd";
import MoveDocumentModal from "@/components/knowledge/MoveDocumentModal";
import type { DocumentFolderTreeNode } from "@/types/folder";

const sampleFolders: DocumentFolderTreeNode[] = [
  {
    id: 10,
    parent_id: null,
    name: "API",
    order_index: 0,
    document_count: 5,
    children: [],
  },
  {
    id: 20,
    parent_id: null,
    name: "FAQ",
    order_index: 10,
    document_count: 2,
    children: [],
  },
];

describe("MoveDocumentModal", () => {
  it("标题里展示 documentId", () => {
    render(
      <ConfigProvider button={{ autoInsertSpace: false }}>
        <App>
          <MoveDocumentModal
            open
            documentId={42}
            currentFolderId={null}
            folders={[]}
            onCancel={vi.fn()}
            onSubmit={vi.fn()}
          />
        </App>
      </ConfigProvider>
    );
    expect(screen.getByText(/移动文档 \(#42\)/)).toBeTruthy();
  });

  it("documentName 传入时在标题下展示文件名", () => {
    render(
      <ConfigProvider button={{ autoInsertSpace: false }}>
        <App>
          <MoveDocumentModal
            open
            documentId={42}
            documentName="api-spec.md"
            currentFolderId={null}
            folders={[]}
            onCancel={vi.fn()}
            onSubmit={vi.fn()}
          />
        </App>
      </ConfigProvider>
    );
    expect(screen.getByText("api-spec.md")).toBeTruthy();
  });

  it("默认选「KB 根目录」+ 不改 → 点「移动」提交 target_folder_id=null", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <ConfigProvider button={{ autoInsertSpace: false }}>
        <App>
          <MoveDocumentModal
            open
            documentId={42}
            currentFolderId={null}
            folders={sampleFolders}
            onCancel={vi.fn()}
            onSubmit={onSubmit}
          />
        </App>
      </ConfigProvider>
    );
    fireEvent.click(screen.getByRole("button", { name: /移动/ }));
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledOnce();
    });
    expect(onSubmit.mock.calls[0][0]).toEqual({ target_folder_id: null });
  });

  it("currentFolderId=10 默认就在「API」上,不改也能提交", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <ConfigProvider button={{ autoInsertSpace: false }}>
        <App>
          <MoveDocumentModal
            open
            documentId={42}
            currentFolderId={10}
            folders={sampleFolders}
            onCancel={vi.fn()}
            onSubmit={onSubmit}
          />
        </App>
      </ConfigProvider>
    );
    fireEvent.click(screen.getByRole("button", { name: /移动/ }));
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledOnce();
    });
    expect(onSubmit.mock.calls[0][0]).toEqual({ target_folder_id: 10 });
  });

  it("点「取消」→ onCancel 调用一次", () => {
    const onCancel = vi.fn();
    render(
      <ConfigProvider button={{ autoInsertSpace: false }}>
        <App>
          <MoveDocumentModal
            open
            documentId={42}
            currentFolderId={null}
            folders={[]}
            onCancel={onCancel}
            onSubmit={vi.fn()}
          />
        </App>
      </ConfigProvider>
    );
    fireEvent.click(screen.getByRole("button", { name: /取消/ }));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});