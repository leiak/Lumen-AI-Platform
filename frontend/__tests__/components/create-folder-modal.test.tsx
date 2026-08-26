// M38.2: CreateFolderModal — name 必填校验 + 父 folder 选择 + 提交 payload。
//
// 覆盖:
// 1. 标题显示当前 KB id
// 2. parent_choice 默认值(defaultParentId 传入时设成该值,否则 "root")
// 3. name 校验失败 → 不调用 onSubmit
// 4. name 填好 → onSubmit 收到 { name, parent_id, order_index, description }

import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ConfigProvider, App } from "antd";
import CreateFolderModal from "@/components/knowledge/CreateFolderModal";
import type { DocumentFolderTreeNode } from "@/types/folder";

const sampleFolders: DocumentFolderTreeNode[] = [
  {
    id: 10,
    parent_id: null,
    name: "API",
    order_index: 0,
    document_count: 5,
    children: [
      {
        id: 11,
        parent_id: 10,
        name: "v1",
        order_index: 0,
        document_count: 2,
        children: [],
      },
    ],
  },
];

describe("CreateFolderModal", () => {
  it("标题里展示 KB id", () => {
    render(
      <ConfigProvider button={{ autoInsertSpace: false }}>
        <App>
          <CreateFolderModal
            open
            kbId={42}
            folders={[]}
            onCancel={vi.fn()}
            onSubmit={vi.fn()}
          />
        </App>
      </ConfigProvider>
    );
    expect(screen.getByText(/新建 folder \(KB #42\)/)).toBeTruthy();
  });

  it("name 为空 → onSubmit 不被调用,显示校验提示", async () => {
    const onSubmit = vi.fn();
    render(
      <ConfigProvider button={{ autoInsertSpace: false }}>
        <App>
          <CreateFolderModal
            open
            kbId={42}
            folders={[]}
            onCancel={vi.fn()}
            onSubmit={onSubmit}
          />
        </App>
      </ConfigProvider>
    );
    fireEvent.click(screen.getByRole("button", { name: /创建/ }));
    await waitFor(() => {
      expect(screen.getByText("请输入 folder 名")).toBeTruthy();
    });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("填好 name → onSubmit 收到 name + parent_id=null (默认 KB 根)", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <ConfigProvider button={{ autoInsertSpace: false }}>
        <App>
          <CreateFolderModal
            open
            kbId={42}
            folders={[]}
            onCancel={vi.fn()}
            onSubmit={onSubmit}
          />
        </App>
      </ConfigProvider>
    );

    fireEvent.change(screen.getByPlaceholderText(/例如/), {
      target: { value: "FAQ" },
    });
    fireEvent.click(screen.getByRole("button", { name: /创建/ }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledOnce();
    });
    const [payload] = onSubmit.mock.calls[0];
    expect(payload.name).toBe("FAQ");
    // parent_choice 默认 "root" → parent_id=null
    expect(payload.parent_id).toBeNull();
    expect(payload.order_index).toBe(0);
  });

  it("defaultParentId 传入时 → 父级默认值是该 id", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <ConfigProvider button={{ autoInsertSpace: false }}>
        <App>
          <CreateFolderModal
            open
            kbId={42}
            folders={sampleFolders}
            defaultParentId={10}
            onCancel={vi.fn()}
            onSubmit={onSubmit}
          />
        </App>
      </ConfigProvider>
    );

    fireEvent.change(screen.getByPlaceholderText(/例如/), {
      target: { value: "sub" },
    });
    fireEvent.click(screen.getByRole("button", { name: /创建/ }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledOnce();
    });
    expect(onSubmit.mock.calls[0][0].parent_id).toBe(10);
  });

  it("点「取消」→ onCancel 调用一次", () => {
    const onCancel = vi.fn();
    render(
      <ConfigProvider button={{ autoInsertSpace: false }}>
        <App>
          <CreateFolderModal
            open
            kbId={42}
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