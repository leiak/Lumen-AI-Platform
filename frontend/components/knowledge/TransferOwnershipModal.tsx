// M38.2.x v2: 转让 workspace 所有权 modal。
//
// Spec §5.1.5: 30 秒延迟生效(防误点)+ 二次输入 workspace 名确认。
// spec §11 风险缓解:任何现有 owner 自动成为 admin(后续手动收回)。

"use client";

import React, { useEffect, useState } from "react";
import {
  Modal,
  Form,
  Select,
  Alert,
  Input,
  Button,
  message as antdMessage,
} from "antd";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import OwnerUserSelect from "@/components/customer/OwnerUserSelect";
import { transferOwnership } from "@/services/workspacePermissions";
import { useCurrentUserWorkspacePermissions } from "@/hooks/useWorkspacePermissions";

export interface TransferOwnershipModalProps {
  open: boolean;
  workspaceId: number;
  workspaceName: string;
  currentOwnerId: number;
  onClose: () => void;
  onSuccess?: (newOwnerId: number) => void;
}

const CONFIRM_WINDOW_SEC = 30;

export function TransferOwnershipModal({
  open,
  workspaceId,
  workspaceName,
  currentOwnerId,
  onClose,
  onSuccess,
}: TransferOwnershipModalProps): React.ReactElement {
  const [newOwnerId, setNewOwnerId] = useState<number | undefined>(undefined);
  const [confirmText, setConfirmText] = useState("");
  const [remaining, setRemaining] = useState(CONFIRM_WINDOW_SEC);
  const queryClient = useQueryClient();
  const { refetch } = useCurrentUserWorkspacePermissions();
  const [form] = Form.useForm();

  // 30s 倒计时 — spec §11 防误点
  useEffect(() => {
    if (!open) {
      setRemaining(CONFIRM_WINDOW_SEC);
      setConfirmText("");
      setNewOwnerId(undefined);
      form.resetFields();
      return;
    }
    setRemaining(CONFIRM_WINDOW_SEC);
    const timer = setInterval(() => {
      setRemaining((r) => (r > 0 ? r - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [open, form]);

  const mutation = useMutation({
    mutationFn: (uid: number) => transferOwnership(workspaceId, { new_owner_id: uid }),
    onSuccess: (_, uid) => {
      antdMessage.success("所有权转让成功");
      queryClient.invalidateQueries({ queryKey: ["auth-me-workspaces"] });
      refetch();
      onSuccess?.(uid);
      onClose();
    },
    onError: (err: Error) => {
      antdMessage.error(err.message || "转让失败");
    },
  });

  const canSubmit =
    typeof newOwnerId === "number" &&
    newOwnerId !== currentOwnerId &&
    confirmText === workspaceName &&
    remaining === 0;

  return (
    <Modal
      open={open}
      title={`转让所有权: ${workspaceName}`}
      okText="确认转让"
      cancelText="取消"
      onCancel={onClose}
      destroyOnClose
      okButtonProps={{
        danger: true,
        disabled: !canSubmit,
        loading: mutation.isPending,
      }}
    >
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="转让所有权是不可逆操作"
        description={
          <>
            <div>原 owner 的 admin 权限会自动保留,但 <code>owner_id</code> 会变更。</div>
            <div style={{ marginTop: 8 }}>
              为防误点,「确认转让」按钮会在 <b>{remaining}</b> 秒后才解锁。
            </div>
          </>
        }
      />
      <Form form={form} layout="vertical">
        <Form.Item label="新 owner" required>
          <OwnerUserSelect value={newOwnerId} onChange={setNewOwnerId} />
          {newOwnerId === currentOwnerId && (
            <Alert
              type="error"
              showIcon
              style={{ marginTop: 8 }}
              message="新 owner 不能是当前 owner"
            />
          )}
        </Form.Item>
        <Form.Item
          label={
            <span>
              输入 workspace 名 <code>{workspaceName}</code> 确认
            </span>
          }
          required
        >
          <Input
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder={workspaceName}
          />
        </Form.Item>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button onClick={onClose}>取消</Button>
          <Button
            danger
            disabled={!canSubmit}
            loading={mutation.isPending}
            onClick={() => newOwnerId && mutation.mutate(newOwnerId)}
          >
            确认转让
            {remaining > 0 && ` (${remaining}s)`}
          </Button>
        </div>
      </Form>
    </Modal>
  );
}