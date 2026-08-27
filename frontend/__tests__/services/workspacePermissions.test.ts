// frontend/__tests__/services/workspacePermissions.test.ts
//
// M38.2.x v2: workspace member / RBAC service + implication helper 单元测试。
//
// - 5 个 endpoint(envelope 解析)走 mock 的 axios。
// - 错误消息提取走 ``extractErrorMessage``(与 wx-publisher 同款契约)。
// - ``effectivePerms`` + ``userHasPermission`` 镜像后端 _PERM_IMPLIES,验证
//   ``kb.update`` → ``kb.read`` + ``document.read`` 等链条。
import { describe, expect, it, vi, beforeEach } from "vitest";

const hoisted = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
  putMock: vi.fn(),
  deleteMock: vi.fn(),
}));

vi.mock("@/services/auth", () => {
  const api = {
    get: hoisted.getMock,
    post: hoisted.postMock,
    put: hoisted.putMock,
    delete: hoisted.deleteMock,
  };
  return { default: api };
});

import {
  effectivePerms,
  inviteMember,
  listMembers,
  fetchMyWorkspacePermissions,
  removeMember,
  transferOwnership,
  updateMember,
  userHasPermission,
} from "@/services/workspacePermissions";

describe("workspacePermissions service — endpoint envelope 解析", () => {
  beforeEach(() => {
    hoisted.getMock.mockReset();
    hoisted.postMock.mockReset();
    hoisted.putMock.mockReset();
    hoisted.deleteMock.mockReset();
  });

  it("listMembers 解包 data.members / data.total", async () => {
    hoisted.getMock.mockResolvedValueOnce({
      data: {
        code: 200,
        message: "ok",
        data: {
          members: [
            {
              user_id: 1,
              username: "alice",
              permissions: ["workspace.read", "kb.read"],
              is_owner: true,
            },
          ],
          total: 1,
        },
      },
    });
    const out = await listMembers(10);
    expect(out.members).toHaveLength(1);
    expect(out.members[0].is_owner).toBe(true);
    expect(hoisted.getMock).toHaveBeenCalledWith("/api/v1/workspaces/10/members");
  });

  it("inviteMember POST 走 /workspaces/{id}/members 整组 payload", async () => {
    hoisted.postMock.mockResolvedValueOnce({
      data: {
        code: 200,
        message: "ok",
        data: {
          user_id: 7,
          username: "bob",
          permissions: ["workspace.read", "kb.read"],
          is_owner: false,
        },
      },
    });
    await inviteMember(10, {
      user_id: 7,
      permissions: ["workspace.read", "kb.read"],
    });
    expect(hoisted.postMock).toHaveBeenCalledWith(
      "/api/v1/workspaces/10/members",
      expect.objectContaining({ user_id: 7 }),
    );
  });

  it("updateMember PUT 走 /workspaces/{id}/members/{uid}", async () => {
    hoisted.putMock.mockResolvedValueOnce({
      data: {
        code: 200,
        message: "ok",
        data: {
          user_id: 7,
          username: "bob",
          permissions: ["kb.update"],
          is_owner: false,
        },
      },
    });
    await updateMember(10, 7, { permissions: ["kb.update"] });
    expect(hoisted.putMock).toHaveBeenCalledWith(
      "/api/v1/workspaces/10/members/7",
      { permissions: ["kb.update"] },
    );
  });

  it("removeMember DELETE → 返 {removed: true}", async () => {
    hoisted.deleteMock.mockResolvedValueOnce({
      data: { code: 200, message: "ok", data: { removed: true } },
    });
    const out = await removeMember(10, 7);
    expect(out.removed).toBe(true);
    expect(hoisted.deleteMock).toHaveBeenCalledWith(
      "/api/v1/workspaces/10/members/7",
    );
  });

  it("transferOwnership POST → 走 /workspaces/{id}/transfer-ownership", async () => {
    hoisted.postMock.mockResolvedValueOnce({
      data: { code: 200, message: "ok", data: { workspace_id: 10, owner_id: 8 } },
    });
    const out = await transferOwnership(10, { new_owner_id: 8 });
    expect(out.owner_id).toBe(8);
    expect(hoisted.postMock).toHaveBeenCalledWith(
      "/api/v1/workspaces/10/transfer-ownership",
      { new_owner_id: 8 },
    );
  });

  it("fetchMyWorkspacePermissions GET → /auth/me/workspaces", async () => {
    hoisted.getMock.mockResolvedValueOnce({
      data: {
        code: 200,
        message: "ok",
        data: {
          workspaces: [{ workspace_id: 10, permissions: ["workspace.read"], is_owner: true }],
        },
      },
    });
    const out = await fetchMyWorkspacePermissions();
    expect(out.workspaces[0].workspace_id).toBe(10);
    expect(hoisted.getMock).toHaveBeenCalledWith("/api/v1/auth/me/workspaces");
  });

  it("4xx detail 是 string → reject 时 Error.message 是 detail", async () => {
    hoisted.getMock.mockResolvedValueOnce({
      data: { detail: "无权限: workspace.manage_members" },
      status: 403,
    });
    await expect(listMembers(10)).rejects.toThrow(
      "无权限: workspace.manage_members",
    );
  });

  it("4xx detail 是 {message: ...} → reject 时 Error.message 是 detail.message", async () => {
    hoisted.getMock.mockResolvedValueOnce({
      data: { detail: { message: "workspace not found" } },
      status: 404,
    });
    await expect(listMembers(999)).rejects.toThrow("workspace not found");
  });

  it("code != 200 + 项目标准信封 message → reject 时是 message", async () => {
    hoisted.getMock.mockResolvedValueOnce({
      data: { code: 500, message: "DB 出错" },
      status: 500,
    });
    await expect(listMembers(10)).rejects.toThrow("DB 出错");
  });
});

describe("effectivePerms —— implication 链镜像后端 _PERM_IMPLIES", () => {
  it("kb.update → {kb.update, kb.read, document.read}", () => {
    const eff = effectivePerms(["kb.update"]);
    expect(eff.has("kb.update")).toBe(true);
    expect(eff.has("kb.read")).toBe(true);
    expect(eff.has("document.read")).toBe(true);
  });

  it("kb.delete 同样含 kb.read + document.read", () => {
    const eff = effectivePerms(["kb.delete"]);
    expect(eff.has("kb.read")).toBe(true);
    expect(eff.has("document.read")).toBe(true);
  });

  it("workspace.update → workspace.read (单跳)", () => {
    const eff = effectivePerms(["workspace.update"]);
    expect(eff.has("workspace.update")).toBe(true);
    expect(eff.has("workspace.read")).toBe(true);
  });

  it("document.move → folder.read + folder.update (双跳)", () => {
    const eff = effectivePerms(["document.move"]);
    expect(eff.has("document.move")).toBe(true);
    expect(eff.has("folder.read")).toBe(true);
    expect(eff.has("folder.update")).toBe(true);
  });

  it("effective_perms 是 fixed point —— effective(perms) === perms", () => {
    const granted = ["kb.delete", "kb.create"];
    const eff = effectivePerms(granted);
    const eff2 = effectivePerms(eff);
    expect([...eff].sort()).toEqual([...eff2].sort());
  });

  it("空集合 → 空 effective set", () => {
    expect(effectivePerms([]).size).toBe(0);
  });
});

describe("userHasPermission —— 通过 effective set 判定", () => {
  it("持有 kb.update 即视作拥有 kb.read + document.read", () => {
    expect(userHasPermission(["kb.update"], "kb.update")).toBe(true);
    expect(userHasPermission(["kb.update"], "kb.read")).toBe(true);
    expect(userHasPermission(["kb.update"], "document.read")).toBe(true);
    expect(userHasPermission(["kb.update"], "kb.delete")).toBe(false);
  });

  it("workspace.read 不 imply 别的 —— 仅包含自身", () => {
    expect(userHasPermission(["workspace.read"], "workspace.update")).toBe(false);
  });
});