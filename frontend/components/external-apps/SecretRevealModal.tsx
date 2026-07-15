"use client";

import { Modal, Alert, Button, Space, Typography } from "antd";
import EmbedSnippetBox from "./EmbedSnippetBox";

const { Paragraph, Text } = Typography;

interface Props {
  open: boolean;
  appKey: string;
  appSecret: string;
  serverUrl: string;
  defaultAgentId?: number;
  onAck: () => void;
}

export default function SecretRevealModal({ open, appKey, appSecret, serverUrl, defaultAgentId, onAck }: Props) {
  return (
    <Modal
      open={open}
      title="⚠️ 请妥善保管以下凭证"
      onCancel={onAck}
      footer={[
        <Button key="ack" type="primary" onClick={onAck}>我已保存,继续</Button>,
      ]}
      closable={false}
      maskClosable={false}
      width={620}
    >
      <Alert
        type="warning"
        showIcon
        message="App Secret 仅此一次显示,关闭后无法再次查看"
        style={{ marginBottom: 16 }}
      />
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <div>
          <Text strong>App Key</Text>
          <Paragraph copyable={{ text: appKey }} style={{ margin: 0 }}>
            <Text code>{appKey}</Text>
          </Paragraph>
          <Text type="secondary">(公开,可嵌入网站)</Text>
        </div>
        <div>
          <Text strong>App Secret</Text>
          <Paragraph copyable={{ text: appSecret }} style={{ margin: 0 }}>
            <Text code>{appSecret}</Text>
          </Paragraph>
          <Text type="secondary">(私密,仅此一次显示)</Text>
        </div>
        <div>
          <Text strong>Widget 嵌入代码片段</Text>
          <EmbedSnippetBox serverUrl={serverUrl} appKey={appKey} defaultAgentId={defaultAgentId} />
        </div>
      </Space>
    </Modal>
  );
}
