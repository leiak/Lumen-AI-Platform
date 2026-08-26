// M38.2: CreateWorkspaceModal — 表单校验 + 提交回调。
//
// 覆盖 4 件事:
// 1. open=false 不渲染表单
// 2. open=true 渲染 name/description/icon/color 4 个字段
// 3. name 为空时 onOk 触发表单校验,onSubmit 不被调用
// 4. name 填好后点「创建」→ onSubmit 拿到 { name, description, icon, color }

import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ConfigProvider, App } from "antd";
import CreateWorkspaceModal from "@/components/knowledge/CreateWorkspaceModal";

describe("CreateWorkspaceModal", () => {
  it("open=false 时不显示表单内容", () => {
    render(
      <ConfigProvider button={{ autoInsertSpace: false }}>
        <App>
          <CreateWorkspaceModal
            open={false}
            onCancel={vi.fn()}
            onSubmit={vi.fn()}
          />
        </App>
      </ConfigProvider>
    );
    expect(screen.queryByText("新建 workspace")).toBeNull();
  });

  it("open=true 时显示 4 个字段(name / 描述 / 图标 / 颜色)", () => {
    render(
      <ConfigProvider button={{ autoInsertSpace: false }}>
        <App>
          <CreateWorkspaceModal
            open
            onCancel={vi.fn()}
            onSubmit={vi.fn()}
          />
        </App>
      </ConfigProvider>
    );
    expect(screen.getByText("新建 workspace")).toBeTruthy();
    expect(screen.getByText("名称")).toBeTruthy();
    expect(screen.getByText("描述")).toBeTruthy();
    expect(screen.getByText("图标")).toBeTruthy();
    expect(screen.getByText("颜色")).toBeTruthy();
  });

  it("name 为空 → onOk 触发校验,onSubmit 不被调用", async () => {
    const onSubmit = vi.fn();
    render(
      <ConfigProvider button={{ autoInsertSpace: false }}>
        <App>
          <CreateWorkspaceModal
            open
            onCancel={vi.fn()}
            onSubmit={onSubmit}
          />
        </App>
      </ConfigProvider>
    );

    fireEvent.click(screen.getByRole("button", { name: /创建/ }));
    await waitFor(() => {
      expect(screen.getByText("请输入 workspace 名")).toBeTruthy();
    });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("填好 name 后点「创建」→ onSubmit 收到完整 payload", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <ConfigProvider button={{ autoInsertSpace: false }}>
        <App>
          <CreateWorkspaceModal
            open
            onCancel={vi.fn()}
            onSubmit={onSubmit}
          />
        </App>
      </ConfigProvider>
    );

    fireEvent.change(screen.getByPlaceholderText(/例如/), {
      target: { value: "研发" },
    });
    fireEvent.click(screen.getByRole("button", { name: /创建/ }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledOnce();
    });
    const [payload] = onSubmit.mock.calls[0];
    expect(payload.name).toBe("研发");
    // icon 有 initialValue = 📁,color 有 initialValue = "#1890ff"
    expect(payload.icon).toBeTruthy();
    expect(payload.color).toBeTruthy();
  });

  it("点「取消」调用 onCancel", () => {
    const onCancel = vi.fn();
    render(
      <ConfigProvider button={{ autoInsertSpace: false }}>
        <App>
          <CreateWorkspaceModal
            open
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