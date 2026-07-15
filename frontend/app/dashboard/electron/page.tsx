"use client";

import { useState, useEffect } from "react";
import {
  Card,
  Form,
  Input,
  Switch,
  Button,
  Space,
  message,
  Table,
  Tag,
  Alert,
  Descriptions,
  Divider,
} from "antd";
import { ReloadOutlined, SaveOutlined, DisconnectOutlined } from "@ant-design/icons";

interface ElectronStatus {
  connected: boolean;
  connection_id: string | null;
  last_heartbeat: string | null;
  version: string;
}

export default function ElectronPage() {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<ElectronStatus>({
    connected: false,
    connection_id: null,
    last_heartbeat: null,
    version: "1.0.0",
  });
  const [wsUrl, setWsUrl] = useState("ws://localhost:11335/api/v1/ws/electron");
  const [commandHistory, setCommandHistory] = useState<any[]>([]);

  const checkConnection = async () => {
    try {
      const response = await fetch("/api/v1/electron/health", {
        headers: { Authorization: `Bearer ${localStorage.getItem("token")}` }
      });
      if (response.ok) {
        const data = await response.json();
        setStatus((prev) => ({ ...prev, connected: true, ...data }));
      } else {
        setStatus((prev) => ({ ...prev, connected: false }));
      }
    } catch (error) {
      setStatus((prev) => ({ ...prev, connected: false }));
    }
  };

  useEffect(() => {
    checkConnection();
    // Poll every 30 seconds
    const interval = setInterval(checkConnection, 30000);
    return () => clearInterval(interval);
  }, []);

  const handleSaveConfig = async () => {
    try {
      localStorage.setItem("electron_ws_url", wsUrl);
      message.success("配置已保存");
    } catch (error) {
      message.error("保存失败");
    }
  };

  const handleTestConnection = async () => {
    setLoading(true);
    try {
      // The actual connection is handled by the Electron desktop app
      // This just validates the URL format
      const url = new URL(wsUrl);
      if (url.protocol === "ws:" || url.protocol === "wss:") {
        message.success("WebSocket URL 格式正确");
      } else {
        message.error("URL 必须是 ws:// 或 wss:// 协议");
      }
    } catch (error) {
      message.error("无效的 WebSocket URL");
    } finally {
      setLoading(false);
    }
  };

  const columns = [
    { title: "时间", dataIndex: "timestamp", key: "timestamp" },
    { title: "类型", dataIndex: "type", key: "type" },
    { title: "命令", dataIndex: "command", key: "command" },
    { title: "状态", dataIndex: "status", key: "status", render: (v: string) => (
      <Tag color={v === "success" ? "green" : v === "error" ? "red" : "orange"}>{v}</Tag>
    )},
  ];

  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 24 }}>
        <Alert
          message="Electron 桌面端配置"
          description="配置 Electron 桌面应用与后端的 WebSocket 连接，以便执行本地命令和文件操作。"
          type="info"
          showIcon
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        <Card title="连接状态" extra={<Button icon={<ReloadOutlined />} onClick={checkConnection}>刷新</Button>}>
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="连接状态">
              <Tag color={status.connected ? "green" : "red"}>
                {status.connected ? "已连接" : "未连接"}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="连接ID">
              {status.connection_id || "-"}
            </Descriptions.Item>
            <Descriptions.Item label="版本">
              {status.version}
            </Descriptions.Item>
            <Descriptions.Item label="最后心跳">
              {status.last_heartbeat || "-"}
            </Descriptions.Item>
          </Descriptions>
          <div style={{ marginTop: 16 }}>
            <Button
              type="primary"
              icon={<DisconnectOutlined />}
              danger
              disabled={!status.connected}
            >
              断开连接
            </Button>
          </div>
        </Card>

        <Card title="WebSocket 配置">
          <Form layout="vertical">
            <Form.Item label="WebSocket 地址" required>
              <Input
                value={wsUrl}
                onChange={(e) => setWsUrl(e.target.value)}
                placeholder="ws://localhost:11335/api/v1/ws/electron"
              />
            </Form.Item>
            <Form.Item>
              <Space>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  onClick={handleSaveConfig}
                >
                  保存配置
                </Button>
                <Button onClick={handleTestConnection} loading={loading}>
                  测试连接
                </Button>
              </Space>
            </Form.Item>
          </Form>
          <Divider />
          <div style={{ fontSize: 12, color: "#888" }}>
            <p><strong>说明：</strong></p>
            <ul style={{ paddingLeft: 16 }}>
              <li>默认地址: ws://localhost:11335/api/v1/ws/electron</li>
              <li>需要在 Electron 桌面应用中启用远程工具</li>
              <li>支持命令执行、文件读写、目录列表功能</li>
            </ul>
          </div>
        </Card>
      </div>

      <Card title="命令历史" style={{ marginTop: 24 }}>
        <Table
          dataSource={commandHistory}
          columns={columns}
          rowKey="id"
          size="small"
          locale={{ emptyText: "暂无命令记录" }}
        />
      </Card>

      <Card title="安全设置" style={{ marginTop: 24 }}>
        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label="路径 Jail">
            <Tag color="green">已启用</Tag>
            <span style={{ marginLeft: 8, fontSize: 12, color: "#888" }}>
              限制命令只能在允许的目录范围内执行
            </span>
          </Descriptions.Item>
          <Descriptions.Item label="命令白名单">
            <Tag color="green">已启用</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="超时限制">
            30 秒
          </Descriptions.Item>
          <Descriptions.Item label="最大输出大小">
            1 MB
          </Descriptions.Item>
        </Descriptions>
      </Card>
    </div>
  );
}
