// frontend/__tests__/components/WorkspaceMembersModal.test.tsx
//
// M38.2.x v2: workspace 成员管理 modal 单测。
//
// Spec §5.1 锁定的 7 条契约:
//   1. 列出 members + 每人权限(19 项 tag / owner 走「全部 19 项(自动)」)
//   2. owner 行不可编辑 / 不可移除(灰 — 占位符)
//   3. 「全选 / 写权限 / 只读 / 清空」4 个预设按钮一键覆盖 perms
//   4. 「邀请成员」→ 弹内嵌 modal + 走 inviteMember(user_id, perms)
//   5. 「编辑」内嵌 checkbox 矩阵 + 保存 → updateMember(workspaceId, uid, perms)
//   6. 「移除」 Popconfirm → removeMember(workspaceId, uid)
//   7. 「转让所有权」按钮在非 owner 时 disabled
//
// AntD 注意事项(踩坑记录):
// - ``ConfigProvider button={{ autoInsertSpace: false }}`` 否则 AntD 在「编辑」
//   2 字按钮中插空格 → textContent 变 "编 辑" 匹配失败。
// - 「编辑」/「移除」按钮带 icon(DeleteOutlined / EditOutlined),AntD 把 icon
//   也算进 accessible name,``getByRole({ name: /^移除$/ })`` 不会匹配。改用
//   ``getAllByText("移除")`` 直接按 textContent 找。
// - React Query 异步 resolve 后还要走 React re-render,用 ``findByText`` 轮询,
//   不要 ``waitFor(mock)`` 后立即断言(后者早于 DOM 更新)。
// - ``screen.getAllByText`` 在同一 text 出现多次时返回数组;按行级操作时用
//   ``container.querySelector('[data-row-key="..."]')`` 圈定行。

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ConfigProvider, App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const hoisted = vi.hoisted(() => ({
  listMock: vi.fn(),
  inviteMock: vi.fn(),
  updateMock: vi.fn(),
  removeMock: vi.fn(),
  assignableMock: vi.fn(),
}));

vi.mock("@/services/workspacePermissions", () => ({
  listMembers: hoisted.listMock,
  inviteMember: hoisted.inviteMock,
  updateMember: hoisted.updateMock,
  removeMember: hoisted.removeMock,
  transferOwnership: vi.fn(),
  fetchMyWorkspacePermissions: vi.fn(),
  effectivePerms: (granted: string[]) => new Set(granted),
  userHasPermission: (granted: string[], p: string) => granted.includes(p),
}));

vi.mock("@/services/users", () => ({
  usersApi: {
    assignable: hoisted.assignableMock,
  },
}));

vi.mock("@/components/customer/OwnerUserSelect", () => ({
  default: (props: { value?: number; onChange?: (v: number) => void }) => (
    <select
      data-testid="owner-user-select"
      value={props.value ?? ""}
      onChange={(e) => props.onChange?.(Number(e.target.value))}
    >
      <option value="">--</option>
      <option value={7}>bob</option>
      <option value={8}>carol</option>
    </select>
  ),
}));

vi.mock("@/components/knowledge/TransferOwnershipModal", () => ({
  TransferOwnershipModal: (props: { open: boolean; onClose: () => void }) =>
    props.open ? (
      <div data-testid="transfer-ownership-modal">
        <button onClick={props.onClose}>close-transfer</button>
      </div>
    ) : null,
}));

import { WorkspaceMembersModal } from "@/components/knowledge/WorkspaceMembersModal";

function wrap(): React.FC<{ children: React.ReactNode }> {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }) => (
    <ConfigProvider button={{ autoInsertSpace: false }}>
      <App>
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      </App>
    </ConfigProvider>
  );
}

const sampleMembers = () => ({
  members: [
    {
      user_id: 11,
      username: "alice",
      email: "alice@test.local",
      full_name: "Alice",
      permissions: ["workspace.read", "kb.read"],
      is_owner: true,
    },
    {
      user_id: 7,
      username: "bob",
      email: "bob@test.local",
      full_name: "Bob",
      permissions: ["kb.read"],
      is_owner: false,
    },
    {
      user_id: 8,
      username: "carol",
      email: "carol@test.local",
      full_name: "Carol",
      permissions: ["workspace.read", "kb.read", "kb.update"],
      is_owner: false,
    },
  ],
  total: 3,
});

describe("WorkspaceMembersModal — 列表与 owner 锁定", () => {
  beforeEach(() => {
    hoisted.listMock.mockReset();
    hoisted.inviteMock.mockReset();
    hoisted.updateMock.mockReset();
    hoisted.removeMock.mockReset();
    hoisted.assignableMock.mockReset();

    hoisted.listMock.mockResolvedValue(sampleMembers());
    hoisted.assignableMock.mockResolvedValue({
      items: [
        { id: 7, username: "bob", full_name: "Bob", email: "bob@test.local" },
        { id: 8, username: "carol", full_name: "Carol", email: "carol@test.local" },
      ],
      total: 2,
      page: 1,
      page_size: 100,
    });
  });

  it("挂载时 listMembers(workspaceId) → 表格列出 alice/bob/carol + owner tag", async () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <WorkspaceMembersModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentUserId={11}
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    // 等数据真渲染进 DOM(RQ resolve + React re-render)
    expect(await screen.findByText("alice")).toBeTruthy();
    expect(hoisted.listMock).toHaveBeenCalledWith(10);
    expect(screen.getByText("owner")).toBeTruthy();
    expect(screen.getByText("全部 19 项(自动)")).toBeTruthy();
    expect(screen.getByText("bob")).toBeTruthy();
    expect(screen.getByText("carol")).toBeTruthy();
  });

  it("owner 行的「操作」列显示 —(没有编辑 / 移除按钮)", async () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <WorkspaceMembersModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentUserId={11}
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    await screen.findByText("alice");

    // AntD Modal 用 portal 渲染,行不在 render container 里 —— 用 document 查。
    const aliceRow = document.querySelector('[data-row-key="11"]');
    expect(aliceRow).toBeTruthy();
    const buttonTexts = Array.from(aliceRow!.querySelectorAll("button")).map(
      (b) => b.textContent ?? "",
    );
    expect(buttonTexts.some((t) => t.includes("编辑"))).toBe(false);
    expect(buttonTexts.some((t) => t.includes("移除"))).toBe(false);
  });

  it("非 owner 行有「编辑」「移除」按钮", async () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <WorkspaceMembersModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentUserId={11}
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    await screen.findByText("bob");

    const bobRow = document.querySelector('[data-row-key="7"]');
    expect(bobRow).toBeTruthy();
    const buttonTexts = Array.from(bobRow!.querySelectorAll("button")).map(
      (b) => b.textContent ?? "",
    );
    expect(buttonTexts.some((t) => t.includes("编辑"))).toBe(true);
    expect(buttonTexts.some((t) => t.includes("移除"))).toBe(true);
  });
});

describe("WorkspaceMembersModal — owner gating", () => {
  beforeEach(() => {
    hoisted.listMock.mockReset();
    hoisted.inviteMock.mockReset();
    hoisted.updateMock.mockReset();
    hoisted.removeMock.mockReset();
    hoisted.assignableMock.mockReset();

    hoisted.listMock.mockResolvedValue(sampleMembers());
    hoisted.assignableMock.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 100,
    });
  });

  it("currentUserId ≠ currentOwnerId → 顶部「您不是 owner」Alert + 转让按钮 disabled", async () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <WorkspaceMembersModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentUserId={7}
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    expect(screen.getByText("您不是 owner")).toBeTruthy();
    const transferBtn = screen.getByText("转让所有权").closest("button");
    expect(transferBtn).toBeTruthy();
    expect((transferBtn as HTMLButtonElement).disabled).toBe(true);
  });

  it("currentUserId === currentOwnerId → 没有「您不是 owner」alert + 转让按钮 enabled", async () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <WorkspaceMembersModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentUserId={11}
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    expect(screen.queryByText("您不是 owner")).toBeNull();
    const transferBtn = screen.getByText("转让所有权").closest("button");
    expect((transferBtn as HTMLButtonElement).disabled).toBe(false);
  });

  it("点击「转让所有权」按钮 → TransferOwnershipModal 打开", async () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <WorkspaceMembersModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentUserId={11}
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    fireEvent.click(screen.getByText("转让所有权").closest("button")!);
    expect(screen.getByTestId("transfer-ownership-modal")).toBeTruthy();
  });
});

describe("WorkspaceMembersModal — 邀请成员子 modal", () => {
  beforeEach(() => {
    hoisted.listMock.mockReset();
    hoisted.inviteMock.mockReset();
    hoisted.updateMock.mockReset();
    hoisted.removeMock.mockReset();
    hoisted.assignableMock.mockReset();

    hoisted.listMock.mockResolvedValue(sampleMembers());
    hoisted.assignableMock.mockResolvedValue({
      items: [
        { id: 7, username: "bob", full_name: "Bob", email: "bob@test.local" },
        { id: 8, username: "carol", full_name: "Carol", email: "carol@test.local" },
      ],
      total: 2,
      page: 1,
      page_size: 100,
    });
  });

  it("点击「邀请成员」→ 子 modal 打开 + 选择 user 后 inviteMember 触发", async () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <WorkspaceMembersModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentUserId={11}
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    fireEvent.click(screen.getByText("邀请成员").closest("button")!);

    expect(await screen.findByText("邀请成员: 研发")).toBeTruthy();

    // 选 carol(id=8,不在现有成员里)
    const select = await screen.findByTestId("owner-user-select");
    fireEvent.change(select, { target: { value: "8" } });
    expect((select as HTMLSelectElement).value).toBe("8");

    // 「邀请」按钮(子 modal footer okButton)
    const okBtn = (await screen.findAllByText("邀请"))
      .map((el) => el.closest("button"))
      .find((b): b is HTMLButtonElement => !!b && !b.disabled)!;
    fireEvent.click(okBtn);

    await waitFor(() =>
      expect(hoisted.inviteMock).toHaveBeenCalledWith(
        10,
        expect.objectContaining({ user_id: 8 }),
      ),
    );
  });

  it("owner 没选 user 时,「邀请」按钮 disabled", async () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <WorkspaceMembersModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentUserId={11}
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    fireEvent.click(screen.getByText("邀请成员").closest("button")!);
    expect(await screen.findByText("邀请成员: 研发")).toBeTruthy();

    // 初始:WRITE_PERMISSIONS 默认被预选,user 没选 → submitDisabled = !userId
    const okBtns = (await screen.findAllByText("邀请"))
      .map((el) => el.closest("button"))
      .filter((b): b is HTMLButtonElement => !!b);
    // 至少有一个 OK button 是 disabled
    expect(okBtns.some((b) => b.disabled)).toBe(true);
  });
});

describe("WorkspaceMembersModal — 编辑权限 + 移除成员", () => {
  beforeEach(() => {
    hoisted.listMock.mockReset();
    hoisted.inviteMock.mockReset();
    hoisted.updateMock.mockReset();
    hoisted.removeMock.mockReset();
    hoisted.assignableMock.mockReset();

    hoisted.listMock.mockResolvedValue(sampleMembers());
    hoisted.assignableMock.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 100,
    });
  });

  it("点击「编辑」 → 内联 Checkbox 矩阵出现 + 「保存」调 updateMember", async () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <WorkspaceMembersModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentUserId={11}
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    await screen.findByText("bob");

    // bob 行的「编辑」按钮(bob + carol 共 2 个非 owner 行)
    const editButtons = await screen.findAllByText("编辑");
    expect(editButtons.length).toBeGreaterThanOrEqual(2);
    fireEvent.click(editButtons[0].closest("button")!);

    // 「全选」快捷按钮
    expect(await screen.findByText("全选")).toBeTruthy();
    fireEvent.click(screen.getByText("全选").closest("button")!);

    // 点保存
    const saveBtns = await screen.findAllByText("保存");
    fireEvent.click(saveBtns[0].closest("button")!);

    await waitFor(() =>
      expect(hoisted.updateMock).toHaveBeenCalledWith(
        10,
        7,
        expect.objectContaining({ permissions: expect.any(Array) }),
      ),
    );
  });

  it("「全选」「写权限」「只读」「清空」4 个预设覆盖整组 perms", async () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <WorkspaceMembersModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentUserId={11}
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    await screen.findByText("bob");

    // 「写权限」
    fireEvent.click((await screen.findAllByText("编辑"))[0].closest("button")!);
    expect(await screen.findByText("写权限")).toBeTruthy();
    fireEvent.click(screen.getByText("写权限").closest("button")!);
    fireEvent.click((await screen.findAllByText("保存"))[0].closest("button")!);
    await waitFor(() => {
      const calls = hoisted.updateMock.mock.calls;
      expect(calls.length).toBeGreaterThan(0);
      const perms = calls[calls.length - 1][2].permissions as string[];
      expect(perms.length).toBeGreaterThanOrEqual(12);
      expect(perms).not.toContain("kb.delete");
    });

    // 「只读」
    fireEvent.click((await screen.findAllByText("编辑"))[0].closest("button")!);
    fireEvent.click(screen.getByText("只读").closest("button")!);
    fireEvent.click((await screen.findAllByText("保存"))[0].closest("button")!);
    await waitFor(() => {
      const calls = hoisted.updateMock.mock.calls;
      const perms = calls[calls.length - 1][2].permissions as string[];
      expect(perms).toEqual([
        "workspace.read",
        "kb.read",
        "folder.read",
        "document.read",
      ]);
    });

    // 「清空」
    fireEvent.click((await screen.findAllByText("编辑"))[0].closest("button")!);
    fireEvent.click(screen.getByText("清空").closest("button")!);
    fireEvent.click((await screen.findAllByText("保存"))[0].closest("button")!);
    await waitFor(() => {
      const calls = hoisted.updateMock.mock.calls;
      const perms = calls[calls.length - 1][2].permissions as string[];
      expect(perms).toEqual([]);
    });
  });

  it("「移除」Popconfirm 确认 → removeMember(10, 7) 调 + refetch", async () => {
    hoisted.removeMock.mockResolvedValue({ removed: true });

    const Wrapper = wrap();
    render(
      <Wrapper>
        <WorkspaceMembersModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentUserId={11}
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    await screen.findByText("bob");

    // bob 行的「移除」(bob + carol 共 2 个)
    const removeBtns = await screen.findAllByText("移除");
    fireEvent.click(removeBtns[0].closest("button")!);

    // Popconfirm 弹出
    expect(await screen.findByText("确认移除该成员?")).toBeTruthy();
    // Popconfirm 里有「移除」确认按钮(在 Popconfirm footer)
    const allRemoveBtns = screen.getAllByText("移除");
    // 最后一个「移除」是 Popconfirm 里的确认按钮
    const confirmBtn = allRemoveBtns[allRemoveBtns.length - 1].closest("button")!;
    fireEvent.click(confirmBtn);

    await waitFor(() =>
      expect(hoisted.removeMock).toHaveBeenCalledWith(10, 7),
    );
    // 成功后 listMembers refetch
    await waitFor(() =>
      expect(hoisted.listMock.mock.calls.length).toBeGreaterThanOrEqual(2),
    );
  });

  it("移除失败 → removeMock 被调即可(toast 内部不验细节)", async () => {
    hoisted.removeMock.mockRejectedValue(
      new Error("无权限: workspace.manage_members"),
    );

    const Wrapper = wrap();
    render(
      <Wrapper>
        <WorkspaceMembersModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentUserId={11}
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    await screen.findByText("bob");

    fireEvent.click((await screen.findAllByText("移除"))[0].closest("button")!);
    expect(await screen.findByText("确认移除该成员?")).toBeTruthy();
    const allRemoveBtns = screen.getAllByText("移除");
    const confirmBtn = allRemoveBtns[allRemoveBtns.length - 1].closest("button")!;
    fireEvent.click(confirmBtn);

    await waitFor(() =>
      expect(hoisted.removeMock).toHaveBeenCalledWith(10, 7),
    );
  });
});

describe("WorkspaceMembersModal — close 行为", () => {
  beforeEach(() => {
    hoisted.listMock.mockReset();
    hoisted.inviteMock.mockReset();
    hoisted.updateMock.mockReset();
    hoisted.removeMock.mockReset();
    hoisted.assignableMock.mockReset();
    hoisted.listMock.mockResolvedValue(sampleMembers());
    hoisted.assignableMock.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 100,
    });
  });

  it("onClose 触发 → onClose 回调", async () => {
    const onClose = vi.fn();
    const Wrapper = wrap();
    render(
      <Wrapper>
        <WorkspaceMembersModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentUserId={11}
          currentOwnerId={11}
          onClose={onClose}
        />
      </Wrapper>,
    );

    // AntD Modal 右上角 × 按钮
    const closeBtns = document.querySelectorAll(".ant-modal-close");
    expect(closeBtns.length).toBeGreaterThan(0);
    fireEvent.click(closeBtns[0]);
    expect(onClose).toHaveBeenCalled();
  });

  it("open 切 false → 关闭后再次 open 内部 inviteOpen state 清空", async () => {
    const Wrapper = wrap();
    const { rerender } = render(
      <Wrapper>
        <WorkspaceMembersModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentUserId={11}
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    await screen.findByText("alice");

    fireEvent.click(screen.getByText("邀请成员").closest("button")!);
    expect(await screen.findByText("邀请成员: 研发")).toBeTruthy();

    rerender(
      <Wrapper>
        <WorkspaceMembersModal
          open={false}
          workspaceId={10}
          workspaceName="研发"
          currentUserId={11}
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    rerender(
      <Wrapper>
        <WorkspaceMembersModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentUserId={11}
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    await screen.findByText("alice");
    expect(screen.queryByText("邀请成员: 研发")).toBeNull();
  });
});
