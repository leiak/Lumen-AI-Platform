// frontend/__tests__/components/TransferOwnershipModal.test.tsx
//
// M38.2.x v2: TransferOwnershipModal 单测(spec §5.1.5)。
//
// 锁定的契约:
//   1. open=true → 弹 modal + 显示「转让所有权: <name>」标题 + 倒计时显示
//   2. 「确认转让」按钮 30s 内 disabled(防误点,spec §11)
//   3. 必须同时满足 3 个条件才能 enable: 选了 user 且 ≠ current_owner +
//      二次输入的 confirmText 完全等于 workspaceName + 倒计时归零
//   4. 选了 current owner 自身 → 显示「不能是当前 owner」错误 alert
//   5. 点「确认转让」→ transferOwnership(workspaceId, { new_owner_id })
//   6. 成功后 onSuccess(newOwnerId) + onClose() 调 + 关闭 modal
//   7. 失败 → 错误留在 modal(不关),toast 由 mutation 内部触发

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { ConfigProvider, App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const hoisted = vi.hoisted(() => ({
  transferMock: vi.fn(),
  fetchMyMock: vi.fn(),
}));

vi.mock("@/services/workspacePermissions", () => ({
  transferOwnership: hoisted.transferMock,
  fetchMyWorkspacePermissions: hoisted.fetchMyMock,
  effectivePerms: (g: string[]) => new Set(g),
  userHasPermission: (g: string[], p: string) => g.includes(p),
  listMembers: vi.fn(),
  inviteMember: vi.fn(),
  updateMember: vi.fn(),
  removeMember: vi.fn(),
}));

// OwnerUserSelect mock 成简单 select,便于精确控制选谁
vi.mock("@/components/customer/OwnerUserSelect", () => ({
  default: (props: { value?: number; onChange?: (v: number) => void }) => (
    <select
      data-testid="new-owner-select"
      value={props.value ?? ""}
      onChange={(e) => props.onChange?.(Number(e.target.value))}
    >
      <option value="">--</option>
      <option value={7}>bob</option>
      <option value={8}>carol</option>
      <option value={11}>alice (current owner)</option>
    </select>
  ),
}));

import { TransferOwnershipModal } from "@/components/knowledge/TransferOwnershipModal";

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

/** 把 30s 倒计时跑完(spec §11 防误点)。 */
async function fastForwardTimer(): Promise<void> {
  await act(async () => {
    vi.advanceTimersByTime(31_000);
  });
}

/** 拿「确认转让」按钮 — 文本在 `<span>` 里,得 closest 到 button。 */
function getConfirmButton(): HTMLButtonElement {
  const span = screen
    .getAllByText(/确认转让/)
    .find((el) => el.tagName === "SPAN");
  expect(span).toBeTruthy();
  const btn = span!.closest("button") as HTMLButtonElement;
  expect(btn).toBeTruthy();
  return btn;
}

describe("TransferOwnershipModal — 渲染 + 倒计时", () => {
  beforeEach(() => {
    hoisted.transferMock.mockReset();
    hoisted.fetchMyMock.mockReset();
    hoisted.fetchMyMock.mockResolvedValue({ workspaces: [] });
    vi.useFakeTimers();
  });

  it("open=true → 渲染 modal + 显示标题「转让所有权: <name>」+ 倒计时初始值", () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <TransferOwnershipModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    expect(screen.getByText(/转让所有权: 研发/)).toBeTruthy();
    // 倒计时初始显示(> 0)
    expect(screen.getByText(/\d+s/)).toBeTruthy();
  });

  it("open=false → 不渲染 modal body(transition 处理后)", () => {
    const Wrapper = wrap();
    const { rerender } = render(
      <Wrapper>
        <TransferOwnershipModal
          open={false}
          workspaceId={10}
          workspaceName="研发"
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    expect(screen.queryByText(/转让所有权: 研发/)).toBeNull();
  });

  it("30s 内「确认转让」disabled(防误点)", () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <TransferOwnershipModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    // 选个 user(非 current owner)
    fireEvent.change(screen.getByTestId("new-owner-select"), { target: { value: "7" } });
    fireEvent.change(screen.getByPlaceholderText("研发"), {
      target: { value: "研发" },
    });

    // 倒计时还没跑完 → button 仍 disabled
    const btn = getConfirmButton();
    expect(btn.disabled).toBe(true);
  });
});

describe("TransferOwnershipModal — enable 条件 3 件套", () => {
  beforeEach(() => {
    hoisted.transferMock.mockReset();
    hoisted.fetchMyMock.mockReset();
    hoisted.fetchMyMock.mockResolvedValue({ workspaces: [] });
    vi.useFakeTimers();
  });

  it("没选 user → 30s 后仍 disabled", async () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <TransferOwnershipModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    fireEvent.change(screen.getByPlaceholderText("研发"), {
      target: { value: "研发" },
    });
    await fastForwardTimer();

    const btn = getConfirmButton();
    expect(btn.disabled).toBe(true);
  });

  it("选了 user 但 confirmText 没匹配 → 30s 后仍 disabled", async () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <TransferOwnershipModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    fireEvent.change(screen.getByTestId("new-owner-select"), { target: { value: "7" } });
    fireEvent.change(screen.getByPlaceholderText("研发"), {
      target: { value: "研发123" }, // 错的输入
    });
    await fastForwardTimer();

    const btn = getConfirmButton();
    expect(btn.disabled).toBe(true);
  });

  it("选了 user + confirmText 匹配 + 30s 跑完 → button enabled", async () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <TransferOwnershipModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    fireEvent.change(screen.getByTestId("new-owner-select"), { target: { value: "7" } });
    fireEvent.change(screen.getByPlaceholderText("研发"), {
      target: { value: "研发" },
    });
    await fastForwardTimer();

    const btn = getConfirmButton();
    expect(btn.disabled).toBe(false);
  });
});

describe("TransferOwnershipModal — owner 自身禁止", () => {
  beforeEach(() => {
    hoisted.transferMock.mockReset();
    hoisted.fetchMyMock.mockReset();
    hoisted.fetchMyMock.mockResolvedValue({ workspaces: [] });
    vi.useFakeTimers();
  });

  it("选了 current owner 自身 → 显示「不能是当前 owner」alert", () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <TransferOwnershipModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    // 选 alice(=current owner)
    fireEvent.change(screen.getByTestId("new-owner-select"), {
      target: { value: "11" },
    });

    expect(screen.getByText(/新 owner 不能是当前 owner/)).toBeTruthy();
  });

  it("即使 30s 跑完 + confirmText 匹配,选了 current owner 自身 → button 仍 disabled", async () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <TransferOwnershipModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    fireEvent.change(screen.getByTestId("new-owner-select"), { target: { value: "11" } });
    fireEvent.change(screen.getByPlaceholderText("研发"), {
      target: { value: "研发" },
    });
    await fastForwardTimer();

    const btn = getConfirmButton();
    expect(btn.disabled).toBe(true);
  });
});

describe("TransferOwnershipModal — submit flow", () => {
  beforeEach(() => {
    hoisted.transferMock.mockReset();
    hoisted.fetchMyMock.mockReset();
    hoisted.fetchMyMock.mockResolvedValue({ workspaces: [] });
    vi.useFakeTimers();
  });

  it("3 件套齐 → 点「确认转让」→ transferOwnership + onSuccess(newOwnerId) + onClose", async () => {
    hoisted.transferMock.mockResolvedValue({ workspace_id: 10, owner_id: 7 });
    const onSuccess = vi.fn();
    const onClose = vi.fn();

    const Wrapper = wrap();
    render(
      <Wrapper>
        <TransferOwnershipModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentOwnerId={11}
          onClose={onClose}
          onSuccess={onSuccess}
        />
      </Wrapper>,
    );

    fireEvent.change(screen.getByTestId("new-owner-select"), { target: { value: "7" } });
    fireEvent.change(screen.getByPlaceholderText("研发"), {
      target: { value: "研发" },
    });
    await fastForwardTimer();

    // 切回 real timers —— react-query 的 mutation 用 setTimeout 调度 onSuccess,
    // fake timers 会让 await 永远不返回。
    vi.useRealTimers();

    const btn = getConfirmButton();
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);

    await waitFor(() =>
      expect(hoisted.transferMock).toHaveBeenCalledWith(10, { new_owner_id: 7 }),
    );
    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith(7));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("transferOwnership 失败 → modal 不关,error 留 modal(由内部 toast 处理)", async () => {
    hoisted.transferMock.mockRejectedValue(new Error("新 owner 不存在"));
    const onSuccess = vi.fn();
    const onClose = vi.fn();

    const Wrapper = wrap();
    render(
      <Wrapper>
        <TransferOwnershipModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentOwnerId={11}
          onClose={onClose}
          onSuccess={onSuccess}
        />
      </Wrapper>,
    );

    fireEvent.change(screen.getByTestId("new-owner-select"), { target: { value: "7" } });
    fireEvent.change(screen.getByPlaceholderText("研发"), {
      target: { value: "研发" },
    });
    await fastForwardTimer();

    vi.useRealTimers();

    const btn = getConfirmButton();
    fireEvent.click(btn);

    await waitFor(() =>
      expect(hoisted.transferMock).toHaveBeenCalledWith(10, { new_owner_id: 7 }),
    );
    // 失败时不调 onSuccess / onClose
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("TransferOwnershipModal — 关闭 + reset", () => {
  beforeEach(() => {
    hoisted.transferMock.mockReset();
    hoisted.fetchMyMock.mockReset();
    hoisted.fetchMyMock.mockResolvedValue({ workspaces: [] });
    vi.useFakeTimers();
  });

  it("点「取消」→ onClose 调", () => {
    const onClose = vi.fn();
    const Wrapper = wrap();
    render(
      <Wrapper>
        <TransferOwnershipModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentOwnerId={11}
          onClose={onClose}
        />
      </Wrapper>,
    );

    // footer 的「取消」button(不是 modal 角落 X)
    const cancelBtn = screen
      .getAllByText("取消")
      .find((el) => el.tagName === "SPAN")
      ?.closest("button");
    expect(cancelBtn).toBeTruthy();
    fireEvent.click(cancelBtn!);
    expect(onClose).toHaveBeenCalled();
  });

  it("open 切 false → 重新 open 时倒计时从 30s 重置 + confirmText 清空", async () => {
    const Wrapper = wrap();
    const { rerender } = render(
      <Wrapper>
        <TransferOwnershipModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    // 用户输入了一些状态
    fireEvent.change(screen.getByTestId("new-owner-select"), { target: { value: "7" } });
    fireEvent.change(screen.getByPlaceholderText("研发"), {
      target: { value: "研发" },
    });
    await fastForwardTimer();

    // 关
    rerender(
      <Wrapper>
        <TransferOwnershipModal
          open={false}
          workspaceId={10}
          workspaceName="研发"
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    // 再开
    rerender(
      <Wrapper>
        <TransferOwnershipModal
          open
          workspaceId={10}
          workspaceName="研发"
          currentOwnerId={11}
          onClose={vi.fn()}
        />
      </Wrapper>,
    );

    // 倒计时从 30 重置(显示 30s)
    expect(screen.getByText(/30s/)).toBeTruthy();
    // confirmText 已被清空 —— placeholder 还能匹配到
    const input = screen.getByPlaceholderText("研发") as HTMLInputElement;
    expect(input.value).toBe("");
    // new owner 也被重置
    const select = screen.getByTestId("new-owner-select") as HTMLSelectElement;
    expect(select.value).toBe("");
  });
});
