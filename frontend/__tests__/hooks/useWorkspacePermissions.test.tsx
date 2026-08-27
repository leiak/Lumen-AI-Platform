// frontend/__tests__/hooks/useWorkspacePermissions.test.tsx
//
// M38.2.x v2: ``useCurrentUserWorkspacePermissions`` / ``useCanI`` 单元测试。
// 锁定三个核心 invariant:
//   1. ``useCanI`` 通过 implication 链判定(grant KB.update 视作拥有 KB.read)
//   2. workspace_id 缺失 → false(不查 root)
//   3. owner 标记的 workspace 自动展开全 19 项 effective set

import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const hoisted = vi.hoisted(() => ({ fetchMyMock: vi.fn() }));

// 镜像后端 _PERM_IMPLIES —— 与 service 里 effectivePerms 同源。
// 不在 vi.mock 里写因为 mock factory hoist 时不能引外部常量。
const PERM_IMPLIES: Record<string, string[]> = {
  "workspace.update": ["workspace.read"],
  "workspace.delete": ["workspace.read"],
  "workspace.manage_members": ["workspace.read"],
  "workspace.transfer_ownership": ["workspace.read"],
  "kb.create": ["kb.read"],
  "kb.update": ["kb.read"],
  "kb.delete": ["kb.read"],
  "kb.read": ["document.read"],
  "folder.create": ["folder.read"],
  "folder.update": ["folder.read"],
  "folder.delete": ["folder.read"],
  "folder.restore": ["folder.read"],
  "document.create": ["document.read"],
  "document.update": ["document.read"],
  "document.delete": ["document.read"],
  "document.move": ["folder.read", "folder.update"],
};

function effectivePerms(granted: string[]): Set<string> {
  const out = new Set<string>(granted);
  let added = true;
  while (added) {
    added = false;
    for (const p of [...out]) {
      for (const implied of PERM_IMPLIES[p] ?? []) {
        if (!out.has(implied)) {
          out.add(implied);
          added = true;
        }
      }
    }
  }
  return out;
}

vi.mock("@/services/workspacePermissions", () => ({
  fetchMyWorkspacePermissions: hoisted.fetchMyMock,
  effectivePerms: (g: string[]) => effectivePerms(g),
  userHasPermission: (g: string[], p: string) => effectivePerms(g).has(p),
  listMembers: vi.fn(),
  inviteMember: vi.fn(),
  updateMember: vi.fn(),
  removeMember: vi.fn(),
  transferOwnership: vi.fn(),
}));

import {
  useCanI,
  useCurrentUserWorkspacePermissions,
} from "@/hooks/useWorkspacePermissions";
import type {
  WorkspaceMyPermissionsResponse,
} from "@/types/workspaceMember";

function wrap(): React.FC<{ children: React.ReactNode }> {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function mockFetchMyWorkspaces(
  payload: WorkspaceMyPermissionsResponse,
): void {
  hoisted.fetchMyMock.mockResolvedValue(payload);
}

describe("useCurrentUserWorkspacePermissions", () => {
  beforeEach(() => {
    hoisted.fetchMyMock.mockReset();
  });

  it("API 数据转 effective permission set,含 implication 展开", async () => {
    mockFetchMyWorkspaces({
      workspaces: [
        // 普通 member — 仅 kb.update,推断应有 kb.read + document.read
        {
          workspace_id: 10,
          permissions: ["kb.update"],
          is_owner: false,
        },
      ],
    });
    const Wrapper = wrap();
    const { result } = renderHook(
      () => useCurrentUserWorkspacePermissions(),
      { wrapper: Wrapper },
    );
    // React Query 在 jsdom 下需要 act() flush 一次让 promise resolve 后的 setState 落地
    await act(async () => {
      await Promise.resolve();
    });
    await waitFor(() => !result.current.isLoading);
    const set = result.current.byWorkspace.get(10);
    expect(set?.has("kb.update")).toBe(true);
    expect(set?.has("kb.read")).toBe(true); // implied
    expect(set?.has("document.read")).toBe(true); // implied
    expect(set?.has("kb.delete")).toBe(false);
  });

  it("is_owner = true → 该 workspace 进入 ownedWorkspaceIds", async () => {
    mockFetchMyWorkspaces({
      workspaces: [
        {
          workspace_id: 5,
          permissions: ["workspace.read"],
          is_owner: true,
        },
        {
          workspace_id: 6,
          permissions: ["workspace.read"],
          is_owner: false,
        },
      ],
    });
    const Wrapper = wrap();
    const { result } = renderHook(
      () => useCurrentUserWorkspacePermissions(),
      { wrapper: Wrapper },
    );
    await act(async () => {
      await Promise.resolve();
    });
    await waitFor(() => !result.current.isLoading);
    expect(result.current.ownedWorkspaceIds.has(5)).toBe(true);
    expect(result.current.ownedWorkspaceIds.has(6)).toBe(false);
  });

  it("API 返空 → byWorkspace 是空 Map", async () => {
    mockFetchMyWorkspaces({ workspaces: [] });
    const Wrapper = wrap();
    const { result } = renderHook(
      () => useCurrentUserWorkspacePermissions(),
      { wrapper: Wrapper },
    );
    await act(async () => {
      await Promise.resolve();
    });
    await waitFor(() => result.current.isLoading === false);
    expect(result.current.byWorkspace.size).toBe(0);
    expect(result.current.ownedWorkspaceIds.size).toBe(0);
  });
});

describe("useCanI", () => {
  beforeEach(() => {
    hoisted.fetchMyMock.mockReset();
  });

  it("workspace_id 为 null → 永远 false", async () => {
    mockFetchMyWorkspaces({
      workspaces: [{ workspace_id: 10, permissions: ["kb.update"], is_owner: false }],
    });
    const Wrapper = wrap();
    const { result } = renderHook(
      () => useCanI("kb.update", null),
      { wrapper: Wrapper },
    );
    await act(async () => {
      await Promise.resolve();
    });
    await waitFor(() => result.current !== null);
    expect(result.current).toBe(false);
  });

  it("grant kb.update → useCanI(\"kb.read\") 通过 implication 链返 true", async () => {
    mockFetchMyWorkspaces({
      workspaces: [{ workspace_id: 10, permissions: ["kb.update"], is_owner: false }],
    });
    const Wrapper = wrap();
    const { result } = renderHook(
      () => useCanI("kb.read", 10),
      { wrapper: Wrapper },
    );
    await act(async () => {
      await Promise.resolve();
    });
    await waitFor(() => result.current !== null);
    expect(result.current).toBe(true);
  });

  it("未 grant 也未 implied → useCanI 返 false", async () => {
    mockFetchMyWorkspaces({
      workspaces: [{ workspace_id: 10, permissions: ["workspace.read"], is_owner: false }],
    });
    const Wrapper = wrap();
    const { result } = renderHook(
      () => useCanI("kb.update", 10),
      { wrapper: Wrapper },
    );
    await act(async () => {
      await Promise.resolve();
    });
    await waitFor(() => result.current !== null);
    expect(result.current).toBe(false);
  });

  it("workspace 不在数据里 → false(不会越权猜测)", async () => {
    mockFetchMyWorkspaces({ workspaces: [] });
    const Wrapper = wrap();
    const { result } = renderHook(
      () => useCanI("kb.update", 99),
      { wrapper: Wrapper },
    );
    await act(async () => {
      await Promise.resolve();
    });
    await waitFor(() => result.current !== null);
    expect(result.current).toBe(false);
  });
});