"use client";

import {
  Row,
  Col,
  Card,
  Statistic,
  List,
  Avatar,
  Tag,
  Typography,
  Spin,
  message,
} from "antd";
import {
  BookOutlined,
  RobotOutlined,
  ShareAltOutlined,
  CloudServerOutlined,
  MessageOutlined,
  SafetyOutlined,
} from "@ant-design/icons";
import { useEffect, useState } from "react";
import { dashboardApi } from "@/services/dashboard";

const { Title, Text } = Typography;

const features = [
  {
    title: "知识库",
    description: "支持 PDF、DOCX、TXT、HTML 文档解析与向量化存储",
    icon: <BookOutlined style={{ fontSize: 32, color: "#1890ff" }} />,
    color: "#e6f7ff",
  },
  {
    title: "AI Agent",
    description: "基于 LangChain 的智能代理，支持多种工具调用",
    icon: <RobotOutlined style={{ fontSize: 32, color: "#52c41a" }} />,
    color: "#f6ffed",
  },
  {
    title: "工作流",
    description: "可视化流程编排，灵活配置 AI 任务流程",
    icon: <ShareAltOutlined style={{ fontSize: 32, color: "#722ed1" }} />,
    color: "#f9f0ff",
  },
  {
    title: "MCP",
    description: "模型上下文协议集成，扩展 AI 能力",
    icon: <CloudServerOutlined style={{ fontSize: 32, color: "#fa8c16" }} />,
    color: "#fff7e6",
  },
];

const recentActivities = [
  {
    title: "知识库更新",
    description: "新增 12 篇文档",
    time: "5 分钟前",
  },
  {
    title: "工作流执行",
    description: "自动化流程已完成",
    time: "15 分钟前",
  },
  {
    title: "Agent 会话",
    description: "新对话创建",
    time: "30 分钟前",
  },
];

const quickActions = [
  { label: "上传文档", icon: <BookOutlined />, color: "#1890ff" },
  { label: "新建 Agent", icon: <RobotOutlined />, color: "#52c41a" },
  { label: "创建工作流", icon: <ShareAltOutlined />, color: "#722ed1" },
  { label: "MCP 设置", icon: <CloudServerOutlined />, color: "#fa8c16" },
];

interface StatsData {
  agent_count: number;
  knowledge_count: number;
  conversation_count: number;
  workflow_count: number;
}

export default function DashboardPage() {
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<StatsData>({
    agent_count: 0,
    knowledge_count: 0,
    conversation_count: 0,
    workflow_count: 0,
  });

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const response = await dashboardApi.getStats();
        if (response.data.code === 200 && response.data.data) {
          setStats(response.data.data);
        }
      } catch (error) {
        message.error("获取仪表盘数据失败，请稍后重试");
      } finally {
        setLoading(false);
      }
    };

    fetchStats();
  }, []);

  return (
    <div style={{ padding: 24 }}>
      <Title level={2}>欢迎使用 Lumen AI Platform</Title>
      <Text type="secondary">基于 LangChain + React 的智能中台平台</Text>

      {/* Statistics */}
      <Row gutter={16} style={{ marginTop: 24 }}>
        <Col span={6}>
          <Card>
            {loading ? (
              <Spin size="small" />
            ) : (
              <Statistic
                title="知识库文档"
                value={stats.knowledge_count}
                prefix={<BookOutlined />}
              />
            )}
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            {loading ? (
              <Spin size="small" />
            ) : (
              <Statistic
                title="Agent 数量"
                value={stats.agent_count}
                prefix={<RobotOutlined />}
              />
            )}
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            {loading ? (
              <Spin size="small" />
            ) : (
              <Statistic
                title="工作流"
                value={stats.workflow_count}
                prefix={<ShareAltOutlined />}
              />
            )}
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            {loading ? (
              <Spin size="small" />
            ) : (
              <Statistic
                title="对话数"
                value={stats.conversation_count}
                prefix={<MessageOutlined />}
              />
            )}
          </Card>
        </Col>
      </Row>

      {/* Features */}
      <Title level={4} style={{ marginTop: 32 }}>
        核心功能
      </Title>
      <Row gutter={16}>
        {features.map((feature, index) => (
          <Col span={6} key={index}>
            <Card
              hoverable
              style={{ backgroundColor: feature.color, border: "none" }}
            >
              <div style={{ textAlign: "center", padding: 16 }}>
                {feature.icon}
                <Title level={5} style={{ marginTop: 12 }}>
                  {feature.title}
                </Title>
                <Text type="secondary">{feature.description}</Text>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      {/* Recent Activity & Quick Actions */}
      <Row gutter={16} style={{ marginTop: 32 }}>
        <Col span={12}>
          <Card title="最近活动" extra={<a href="#">查看更多</a>}>
            <List
              itemLayout="horizontal"
              dataSource={recentActivities}
              renderItem={(item) => (
                <List.Item>
                  <List.Item.Meta
                    avatar={
                      <Avatar
                        icon={<SafetyOutlined />}
                        style={{ backgroundColor: "#1890ff" }}
                      />
                    }
                    title={item.title}
                    description={item.description}
                  />
                  <Tag>{item.time}</Tag>
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="快捷操作">
            <Row gutter={16}>
              {quickActions.map((action, index) => (
                <Col span={12} key={index} style={{ marginBottom: 16 }}>
                  <Card
                    hoverable
                    style={{ textAlign: "center" }}
                    styles={{ header: { backgroundColor: action.color, color: "#fff" } }}
                  >
                    {action.icon}
                    <div style={{ marginTop: 8 }}>{action.label}</div>
                  </Card>
                </Col>
              ))}
            </Row>
          </Card>
        </Col>
      </Row>
    </div>
  );
}