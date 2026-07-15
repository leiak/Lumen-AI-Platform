"use client";

import { useState, useEffect } from "react";
import {
  Table,
  Button,
  Space,
  Modal,
  Form,
  Input,
  message,
  Popconfirm,
  Card,
  Tag,
  Tabs,
  Alert,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { mcpApi, MCPServer, MCPTool, MarketplaceTool } from "@/services/mcp";

interface RegisterToolFormValues {
  name: string;
  description: string;
  server_name: string;
  input_schema: string;
}

export default function MCPPage() {
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [marketplaceTools, setMarketplaceTools] = useState<MarketplaceTool[]>([]);
  const [loading, setLoading] = useState(false);
  const [serverModalVisible, setServerModalVisible] = useState(false);
  const [toolModalVisible, setToolModalVisible] = useState(false);
  const [form] = Form.useForm();
  // Server-side pagination state. /mcp/servers and /mcp/tools both return
  // PaginatedResponse; the previous implementation called them with no
  // page params and the Tables had no `pagination` prop at all, so only
  // the default 10 rows were ever visible.
  const [serverPage, setServerPage] = useState(1);
  const [serverPageSize, setServerPageSize] = useState(10);
  const [serverTotal, setServerTotal] = useState(0);
  const [toolPage, setToolPage] = useState(1);
  const [toolPageSize, setToolPageSize] = useState(10);
  const [toolTotal, setToolTotal] = useState(0);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [serverRes, toolRes] = await Promise.all([
        mcpApi.listServers(serverPage, serverPageSize),
        mcpApi.listTools(toolPage, toolPageSize),
      ]);
      if (serverRes.data.code === 200) {
        setServers(serverRes.data.data || []);
        setServerTotal(serverRes.data.total || 0);
      }
      if (toolRes.data.code === 200) {
        setTools(toolRes.data.data || []);
        setToolTotal(toolRes.data.total || 0);
      }
    } catch (error) {
      message.error("获取数据失败");
    } finally {
      setLoading(false);
    }
  };

  const fetchMarketplaceTools = async () => {
    setLoading(true);
    try {
      const response = await mcpApi.listMarketplaceTools();
      if (response.data.code === 200) {
        setMarketplaceTools(response.data.data);
      }
    } catch (error) {
      message.error("获取工具市场失败");
    } finally {
      setLoading(false);
    }
  };

  const handleInstallTool = async (toolName: string) => {
    // M30 P1-3: Backend doesn't yet track installed tools — the install
    // endpoint is a placeholder. The frontend honest-acknowledges this
    // in two places (an Alert at the top of the marketplace tab + a
    // Popconfirm on each install button) so product demos and user
    // expectations stay honest. The TODO is moved to M30+ when the
    // install flow is real.
    try {
      const response = await mcpApi.installMarketplaceTool(toolName);
      if (response.data.code === 200) {
        message.success(`工具 ${toolName} 安装成功(演示)`);
        fetchMarketplaceTools();
      }
    } catch (error) {
      message.error("安装失败");
    }
  };

  useEffect(() => {
    fetchData();
    fetchMarketplaceTools();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverPage, serverPageSize, toolPage, toolPageSize]);

  const handleRegisterServer = async (values: { name: string; url: string }) => {
    try {
      const response = await mcpApi.registerServer(values.name, values.url);
      if (response.data.code === 200) {
        message.success("注册成功");
        setServerModalVisible(false);
        form.resetFields();
        fetchData();
      }
    } catch (error) {
      message.error("注册失败");
    }
  };

  const handleUnregisterServer = async (name: string) => {
    try {
      await mcpApi.unregisterServer(name);
      message.success("取消注册成功");
      fetchData();
    } catch (error) {
      message.error("取消注册失败");
    }
  };

  const handleRegisterTool = async (values: RegisterToolFormValues) => {
    try {
      const response = await mcpApi.registerTool({
        name: values.name,
        description: values.description,
        server_name: values.server_name,
        input_schema: JSON.parse(values.input_schema || "{}"),
      });
      if (response.data.code === 200) {
        message.success("注册成功");
        setToolModalVisible(false);
        form.resetFields();
        fetchData();
      }
    } catch (error) {
      message.error("注册失败");
    }
  };

  const serverColumns: ColumnsType<MCPServer> = [
    {
      title: "名称",
      dataIndex: "name",
      key: "name",
    },
    {
      title: "URL",
      dataIndex: "url",
      key: "url",
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      render: (status) => (
        <Tag color={status === "connected" ? "green" : "red"}>{status}</Tag>
      ),
    },
    {
      title: "操作",
      key: "action",
      render: (_, record) => (
        <Popconfirm
          title="确认取消注册?"
          onConfirm={() => handleUnregisterServer(record.name)}
        >
          <Button size="small" danger>
            取消注册
          </Button>
        </Popconfirm>
      ),
    },
  ];

  const toolColumns: ColumnsType<MCPTool> = [
    {
      title: "名称",
      dataIndex: "name",
      key: "name",
    },
    {
      title: "描述",
      dataIndex: "description",
      key: "description",
    },
    {
      title: "服务器",
      dataIndex: "server_name",
      key: "server_name",
    },
  ];

  const marketplaceColumns: ColumnsType<MarketplaceTool> = [
    {
      title: "名称",
      dataIndex: "name",
      key: "name",
    },
    {
      title: "描述",
      dataIndex: "description",
      key: "description",
    },
    {
      title: "类别",
      dataIndex: "category",
      key: "category",
    },
    {
      title: "服务器",
      dataIndex: "server",
      key: "server",
    },
    {
      title: "操作",
      key: "action",
      render: (_, record) => (
        <Popconfirm
          title="演示模式"
          description="工具安装是模拟的 — backend 还没实装 (M30+ 路线图)。现在点击会返 200 但不持久化。"
          okText="我懂,继续"
          cancelText="取消"
        >
          <Button
            size="small"
            type="primary"
            onClick={() => handleInstallTool(record.name)}
          >
            安装(演示)
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Tabs
        defaultActiveKey="servers"
        items={[
          {
            key: "servers",
            label: "MCP 服务器",
            children: (
              <>
                <div style={{ marginBottom: 16 }}>
                  <Button
                    type="primary"
                    icon={<PlusOutlined />}
                    onClick={() => setServerModalVisible(true)}
                  >
                    注册服务器
                  </Button>
                </div>
                <Table
                  columns={serverColumns}
                  dataSource={servers}
                  rowKey="name"
                  loading={loading}
                  pagination={{
                    current: serverPage,
                    pageSize: serverPageSize,
                    total: serverTotal,
                    showSizeChanger: true,
                    showTotal: (t) => `共 ${t} 条`,
                    onChange: (p, ps) => {
                      setServerPage(p);
                      setServerPageSize(ps);
                    },
                  }}
                />
              </>
            ),
          },
          {
            key: "tools",
            label: "MCP 工具",
            children: (
              <>
                <div style={{ marginBottom: 16 }}>
                  <Button
                    type="primary"
                    icon={<PlusOutlined />}
                    onClick={() => setToolModalVisible(true)}
                  >
                    注册工具
                  </Button>
                </div>
                <Table
                  columns={toolColumns}
                  dataSource={tools}
                  rowKey="name"
                  loading={loading}
                  pagination={{
                    current: toolPage,
                    pageSize: toolPageSize,
                    total: toolTotal,
                    showSizeChanger: true,
                    showTotal: (t) => `共 ${t} 条`,
                    onChange: (p, ps) => {
                      setToolPage(p);
                      setToolPageSize(ps);
                    },
                  }}
                />
              </>
            ),
          },
          {
            key: "marketplace",
            label: "工具市场",
            children: (
              <Space direction="vertical" style={{ width: "100%" }}>
                <Alert
                  type="info"
                  showIcon
                  message="工具市场 (演示模式)"
                  description="工具安装是模拟的 — backend 还没装 installed_tools
                  表。当前 '安装' 按钮会返 200 但不持久化。等 M30+ 真实
                  装好再取消本提示。"
                />
                <Table
                  columns={marketplaceColumns}
                  dataSource={marketplaceTools}
                  rowKey="name"
                  loading={loading}
                />
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title="注册 MCP 服务器"
        open={serverModalVisible}
        onCancel={() => {
          setServerModalVisible(false);
          form.resetFields();
        }}
        footer={null}
      >
        <Form form={form} layout="vertical" onFinish={handleRegisterServer}>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: "请输入服务器名称" }]}
          >
            <Input placeholder="请输入服务器名称" />
          </Form.Item>
          <Form.Item
            name="url"
            label="URL"
            rules={[{ required: true, message: "请输入服务器 URL" }]}
          >
            <Input placeholder="http://localhost:8080" />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                注册
              </Button>
              <Button onClick={() => setServerModalVisible(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="注册 MCP 工具"
        open={toolModalVisible}
        onCancel={() => {
          setToolModalVisible(false);
          form.resetFields();
        }}
        footer={null}
      >
        <Form form={form} layout="vertical" onFinish={handleRegisterTool}>
          <Form.Item
            name="name"
            label="工具名称"
            rules={[{ required: true, message: "请输入工具名称" }]}
          >
            <Input placeholder="请输入工具名称" />
          </Form.Item>
          <Form.Item
            name="description"
            label="描述"
            rules={[{ required: true, message: "请输入描述" }]}
          >
            <Input.TextArea placeholder="请输入描述" />
          </Form.Item>
          <Form.Item
            name="server_name"
            label="服务器名称"
            rules={[{ required: true, message: "请输入服务器名称" }]}
          >
            <Input placeholder="请输入服务器名称" />
          </Form.Item>
          <Form.Item name="input_schema" label="输入模式">
            <Input.TextArea placeholder='{"type": "object"}' />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                注册
              </Button>
              <Button onClick={() => setToolModalVisible(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
