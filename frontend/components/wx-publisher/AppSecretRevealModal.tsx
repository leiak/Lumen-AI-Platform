// frontend/components/wx-publisher/AppSecretRevealModal.tsx
// M32 — 公众号助手 — AppSecret 一次性显示 Modal.
//
// Spec §5.6 — 创建成功后弹: 一次性显示明文 + 复制到剪贴板 +
// 我已保存. 不再显示明文后续任何场景.
"use client";

import { useState } from "react";
import { Modal, Button, Input, Space, Alert, Typography } from "antd";
import { CopyOutlined, CheckCircleOutlined } from "@ant-design/icons";

const { Paragraph } = Typography;

interface AppSecretRevealModalProps {
  open: boolean;
  appSecret: string;
  appId: string;
  onClose: () => void;
}

export function AppSecretRevealModal({
  open,
  appSecret,
  appId,
  onClose,
}: AppSecretRevealModalProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(appSecret);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // 浏览器不支持 clipboard API 时用户手动复制.
    }
  };

  return (
    <Modal
      title="请保存 AppSecret"
      open={open}
      onCancel={onClose}
      footer={null}
      width={560}
      maskClosable={false}
    >
      <Alert
        type="warning"
        showIcon
        message="AppSecret 已加密存储, 本次关闭后不再以明文显示."
        style={{ marginBottom: 16 }}
      />
      <Space direction="vertical" style={{ width: "100%" }} size={12}>
        <div>
          <div style={{ fontSize: 12, color: "#666", marginBottom: 4 }}>AppID</div>
          <Input value={appId} readOnly />
        </div>
        <div>
          <div style={{ fontSize: 12, color: "#666", marginBottom: 4 }}>AppSecret</div>
          <Input.Password value={appSecret} readOnly />
        </div>
        <Space>
          <Button
            icon={copied ? <CheckCircleOutlined /> : <CopyOutlined />}
            onClick={handleCopy}
          >
            {copied ? "已复制" : "复制到剪贴板"}
          </Button>
          <Button type="primary" onClick={onClose}>
            我已保存, 关闭
          </Button>
        </Space>
        <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8 }}>
          建议立即记录到团队密码管理器. 若丢失可在账号详情页「重新校验」并重置.
        </Paragraph>
      </Space>
    </Modal>
  );
}

export default AppSecretRevealModal;