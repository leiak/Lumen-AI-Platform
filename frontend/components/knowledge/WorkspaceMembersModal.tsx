// M38.2.x v2: workspace 成员管理 modal。
//
// Spec §5.1:
// - 列出当前 workspace 的全部成员 + 每人权限(19 项 Checkbox 矩阵)
// - 邀请 user(整组权限 — 一次性 set,后续 edit 整组覆盖)
// - 删除 user(member 权限回收,但 owner_id 不动)
// - 转让所有权(独立 TransferOwnershipModal,这里只放按钮入口)
//
// 「全选 / 只读 / 写权限」3 个快捷按钮直接选 READ_ONLY / WRITE / ALL。
// owner 行不能被修改 / 删除 — owner 是 workspace 字段,不是 grant。

"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  Modal,
  Button,
  Form,
  Select,
  Checkbox,
  Space,
  Popconfirm,
  App,
  Table,
  Tag,
  Alert,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  PlusOutlined,
  DeleteOutlined,
  CrownOutlined,
  TeamOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import OwnerUserSelect from "@/components/customer/OwnerUserSelect";
import { TransferOwnershipModal } from "@/components/knowledge/TransferOwnershipModal";
import {
  inviteMember,
  listMembers,
  removeMember,
  updateMember,
} from "@/services/workspacePermissions";
import {
  ALL_PERMISSIONS,
  READ_ONLY_PERMISSIONS,
  WRITE_PERMISSIONS,
} from "@/types/workspaceMember";
import type {
  WorkspaceMember,
  WorkspacePermission,
} from "@/types/workspaceMember";

export interface WorkspaceMembersModalProps {
  open: boolean;
  workspaceId: number;
  workspaceName: string;
  currentUserId: number;
  currentOwnerId: number;
  onClose: () => void;
}

export function WorkspaceMembersModal({
  open,
  workspaceId,
  workspaceName,
  currentUserId,
  currentOwnerId,
  onClose,
}: WorkspaceMembersModalProps): React.ReactElement {
  const queryClient = useQueryClient();
  const { message: toast, modal } = App.useApp();
  const [inviteOpen, setInviteOpen] = useState(false);
  const [transferOpen, setTransferOpen] = useState(false);
  const [editing, setEditing] = useState<{
    user_id: number;
    perms: Set<WorkspacePermission>;
  } | null>(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["workspace-members", workspaceId],
    queryFn: () => listMembers(workspaceId),
    enabled: open,
  });

  useEffect(() => {
    if (!open) {
      setInviteOpen(false);
      setTransferOpen(false);
      setEditing(null);
    }
  }, [open]);

  const removeMutation = useMutation({
    mutationFn: (userId: number) => removeMember(workspaceId, userId),
    onSuccess: () => {
      toast.success("成员已移除");
      queryClient.invalidateQueries({ queryKey: ["workspace-members", workspaceId] });
    },
    onError: (err: Error) => toast.error(err.message || "移除失败"),
  });

  const updateMutation = useMutation({
    mutationFn: (vars: { user_id: number; perms: WorkspacePermission[] }) =>
      updateMember(workspaceId, vars.user_id, { permissions: vars.perms }),
    onSuccess: () => {
      toast.success("权限已更新");
      queryClient.invalidateQueries({ queryKey: ["workspace-members", workspaceId] });
      setEditing(null);
    },
    onError: (err: Error) => toast.error(err.message || "更新失败"),
  });

  const columns: ColumnsType<WorkspaceMember> = useMemo(
    () => [
      {
        title: "成员",
        dataIndex: "user_id",
        render: (uid: number, record) => (
          <Space>
            {record.is_owner && (
              <Tag color="gold" icon={<CrownOutlined />}>
                owner
              </Tag>
            )}
            <span>{record.username}</span>
            {uid === currentUserId && <Tag color="blue">我</Tag>}
          </Space>
        ),
      },
      {
        title: "权限",
        dataIndex: "permissions",
        render: (_perms, record) => {
          if (record.is_owner) {
            return <Tag color="green">全部 19 项(自动)</Tag>;
          }
          const editingThis = editing?.user_id === record.user_id;
          if (!editingThis) {
            return (
              <Space size={4} wrap>
                {record.permissions.slice(0, 4).map((p) => (
                  <Tag key={p}>{p}</Tag>
                ))}
                {record.permissions.length > 4 && (
                  <Tag>+{record.permissions.length - 4}</Tag>
                )}
              </Space>
            );
          }
          return (
            <Space size={4} wrap style={{ maxWidth: 480 }}>
              <Button size="small" onClick={() => applyPreset(editing, "all")}>
                全选
              </Button>
              <Button size="small" onClick={() => applyPreset(editing, "write")}>
                写权限
              </Button>
              <Button size="small" onClick={() => applyPreset(editing, "read")}>
                只读
              </Button>
              <Button size="small" onClick={() => applyPreset(editing, "none")}>
                清空
              </Button>
              {ALL_PERMISSIONS.map((p) => (
                <Checkbox
                  key={p}
                  checked={editing.perms.has(p)}
                  onChange={(e) =>
                    setEditing({
                      user_id: record.user_id,
                      perms: new Set(
                        e.target.checked
                          ? [...editing.perms, p]
                          : [...editing.perms].filter((x) => x !== p),
                      ),
                    })
                  }
                >
                  {p}
                </Checkbox>
              ))}
            </Space>
          );
        },
      },
      {
        title: "操作",
        render: (_v, record) => {
          if (record.is_owner) {
            return <span style={{ color: "#999" }}>—</span>;
          }
          const editingThis = editing?.user_id === record.user_id;
          if (editingThis) {
            return (
              <Space>
                <Button
                  size="small"
                  type="primary"
                  loading={updateMutation.isPending}
                  onClick={() =>
                    updateMutation.mutate({
                      user_id: record.user_id,
                      perms: Array.from(editing.perms),
                    })
                  }
                >
                  保存
                </Button>
                <Button size="small" onClick={() => setEditing(null)}>
                  取消
                </Button>
              </Space>
            );
          }
          return (
            <Space>
              <Button
                size="small"
                onClick={() =>
                  setEditing({
                    user_id: record.user_id,
                    perms: new Set(record.permissions),
                  })
                }
              >
                编辑
              </Button>
              <Popconfirm
                title="确认移除该成员?"
                description="移除后该 user 将失去此 workspace 的全部权限(workspace_id IS NULL 的 KB 仍可读)"
                okText="移除"
                okButtonProps={{ danger: true }}
                cancelText="取消"
                onConfirm={() => removeMutation.mutate(record.user_id)}
              >
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  loading={removeMutation.isPending}
                >
                  移除
                </Button>
              </Popconfirm>
            </Space>
          );
        },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [editing, updateMutation.isPending, removeMutation.isPending],
  );

  function applyPreset(
    e: { user_id: number; perms: Set<WorkspacePermission> },
    preset: "all" | "write" | "read" | "none",
  ) {
    let next: WorkspacePermission[];
    if (preset === "all") next = [...ALL_PERMISSIONS];
    else if (preset === "write") next = [...WRITE_PERMISSIONS];
    else if (preset === "read") next = [...READ_ONLY_PERMISSIONS];
    else next = [];
    setEditing({ user_id: e.user_id, perms: new Set(next) });
  }

  const isCurrentUserOwner = currentOwnerId === currentUserId;

  return (
    <>
      <Modal
        open={open}
        title={
          <Space>
            <TeamOutlined />
            <span>成员管理: {workspaceName}</span>
          </Space>
        }
        onCancel={onClose}
        footer={null}
        width={920}
        destroyOnClose
      >
        {!isCurrentUserOwner && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message="您不是 owner"
            description="仅 owner 可以转让所有权。您仍可被 owner 邀请获得权限。"
          />
        )}
        <Space style={{ marginBottom: 12 }}>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setInviteOpen(true)}
          >
            邀请成员
          </Button>
          <Button
            icon={<SwapOutlined />}
            disabled={!isCurrentUserOwner}
            onClick={() => setTransferOpen(true)}
          >
            转让所有权
          </Button>
        </Space>
        <Table
          rowKey="user_id"
          loading={isLoading}
          dataSource={data?.members ?? []}
          columns={columns}
          pagination={false}
          size="small"
        />
      </Modal>
      <InviteMemberInner
        open={inviteOpen}
        workspaceId={workspaceId}
        workspaceName={workspaceName}
        existingUserIds={new Set((data?.members ?? []).map((m) => m.user_id))}
        onClose={() => setInviteOpen(false)}
        onSuccess={() => {
          setInviteOpen(false);
          refetch();
        }}
      />
      <TransferOwnershipModal
        open={transferOpen}
        workspaceId={workspaceId}
        workspaceName={workspaceName}
        currentOwnerId={currentOwnerId}
        onClose={() => setTransferOpen(false)}
        onSuccess={() => {
          setTransferOpen(false);
          refetch();
          queryClient.invalidateQueries({ queryKey: ["auth-me-workspaces"] });
        }}
      />
    </>
  );
}

// --- 邀请子 modal -------------------------------------------------------

interface InviteMemberInnerProps {
  open: boolean;
  workspaceId: number;
  workspaceName: string;
  existingUserIds: Set<number>;
  onClose: () => void;
  onSuccess?: () => void;
}

function InviteMemberInner({
  open,
  workspaceId,
  workspaceName,
  existingUserIds,
  onClose,
  onSuccess,
}: InviteMemberInnerProps): React.ReactElement {
  const { message: toast } = App.useApp();
  const [userId, setUserId] = useState<number | undefined>(undefined);
  const [perms, setPerms] = useState<Set<WorkspacePermission>>(
    new Set(WRITE_PERMISSIONS),
  );

  useEffect(() => {
    if (!open) {
      setUserId(undefined);
      setPerms(new Set(WRITE_PERMISSIONS));
    }
  }, [open]);

  const mutation = useMutation({
    mutationFn: () =>
      inviteMember(workspaceId, {
        user_id: userId!,
        permissions: Array.from(perms),
      }),
    onSuccess: () => {
      toast.success("已邀请");
      onSuccess?.();
    },
    onError: (err: Error) => toast.error(err.message || "邀请失败"),
  });

  const submitDisabled = !userId || perms.size === 0 || mutation.isPending;

  return (
    <Modal
      open={open}
      title={`邀请成员: ${workspaceName}`}
      onCancel={onClose}
      okText="邀请"
      cancelText="取消"
      okButtonProps={{ disabled: submitDisabled, loading: mutation.isPending }}
      onOk={() => mutation.mutate()}
      destroyOnClose
    >
      <Form layout="vertical">
        <Form.Item label="选择用户" required>
          <OwnerUserSelect value={userId} onChange={setUserId} />
          {userId !== undefined && existingUserIds.has(userId) && (
            <Alert
              type="error"
              showIcon
              style={{ marginTop: 8 }}
              message="该用户已是成员"
            />
          )}
        </Form.Item>
        <Form.Item label="初始权限(整组)" required>
          <Space style={{ marginBottom: 8 }}>
            <Button size="small" onClick={() => setPerms(new Set(ALL_PERMISSIONS))}>
              全选
            </Button>
            <Button size="small" onClick={() => setPerms(new Set(WRITE_PERMISSIONS))}>
              写权限
            </Button>
            <Button size="small" onClick={() => setPerms(new Set(READ_ONLY_PERMISSIONS))}>
              只读
            </Button>
            <Button size="small" onClick={() => setPerms(new Set())}>
              清空
            </Button>
            <span style={{ color: "#999" }}>已选 {perms.size} 项</span>
          </Space>
          <div style={{ maxHeight: 320, overflow: "auto" }}>
            <Space size={4} wrap>
              {ALL_PERMISSIONS.map((p) => (
                <Checkbox
                  key={p}
                  checked={perms.has(p)}
                  onChange={(e) =>
                    setPerms(
                      new Set(
                        e.target.checked
                          ? [...perms, p]
                          : [...perms].filter((x) => x !== p),
                      ),
                    )
                  }
                >
                  {p}
                </Checkbox>
              ))}
            </Space>
          </div>
        </Form.Item>
      </Form>
    </Modal>
  );
}