"use client";

import { useState, useEffect } from "react";
import {
  Table,
  Button,
  Space,
  Switch,
  message,
  Popconfirm,
  Card,
  Avatar,
  List,
  Input,
  Modal,
} from "antd";
import { PlusOutlined, SendOutlined, RobotOutlined, UserOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { agentApi, ChatMessage } from "@/services/agent";
import { modelsApi, ModelConfig } from "@/services/models";
import { AgentFormModal } from "@/components/agent/AgentFormModal";
import { AgentKBBadge } from "@/components/agent/AgentKBBadge";
import { Markdown } from "@/components/chat/Markdown";
import type { Agent } from "@/types/api";

export default function AgentPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(12);
  const [total, setTotal] = useState(0);

  // Create modal
  const [createOpen, setCreateOpen] = useState(false);

  // Edit modal
  const [editOpen, setEditOpen] = useState(false);
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);

  // Chat modal
  const [chatModalVisible, setChatModalVisible] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputMessage, setInputMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [modelConfigs, setModelConfigs] = useState<ModelConfig[]>([]);
  const [conversationId, setConversationId] = useState<number | null>(null);

  // Per-row is_active toggle loading. Keyed by agent id so independent
  // rows can be toggled in parallel without blocking each other.
  const [togglePending, setTogglePending] = useState<Record<number, boolean>>({});

  const fetchAgents = async () => {
    setLoading(true);
    try {
      const response = await agentApi.list(page, pageSize);
      if (response.data.code === 200) {
        setAgents(response.data.data || []);
        setTotal(response.data.total || 0);
      }
    } catch (error) {
      message.error("获取Agent列表失败");
    } finally {
      setLoading(false);
    }
  };

  const fetchModelConfigs = async () => {
    try {
      const response = await modelsApi.list(1, 100);
      if (response.data.code === 200) {
        setModelConfigs(response.data.data);
      }
    } catch (error) {
      message.error("获取模型列表失败");
    }
  };

  useEffect(() => {
    fetchAgents();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize]);

  // Fetch models when create or edit modal opens (AgentFormModal needs them
  // for the model_name select). Skip if we already have them cached to avoid
  // redundant calls across create->edit transitions and re-opens.
  useEffect(() => {
    if ((createOpen || editOpen) && modelConfigs.length === 0) {
      fetchModelConfigs();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [createOpen, editOpen]);

  const handleCreate = () => {
    setCreateOpen(true);
  };

  const handleCreated = () => {
    setCreateOpen(false);
    fetchAgents();
  };

  const handleDelete = async (id: number) => {
    try {
      await agentApi.delete(id);
      message.success("删除成功");
      fetchAgents();
    } catch (error) {
      message.error("删除失败");
    }
  };

  const openEdit = (agent: Agent) => {
    setEditingAgent(agent);
    setEditOpen(true);
  };

  const handleEdited = () => {
    setEditOpen(false);
    setEditingAgent(null);
    fetchAgents();
  };

  const handleToggleActive = async (id: number, checked: boolean) => {
    // Optimistic update: flip local state immediately, then call API.
    // Capture the *actual* prior value during the update callback so the
    // rollback is correct even if state was mutated by a parallel update
    // or pagination refresh in flight.
    let priorActive: boolean | undefined;
    setAgents((prev) =>
      prev.map((a) => {
        if (a.id === id) {
          priorActive = a.is_active;
          return { ...a, is_active: checked };
        }
        return a;
      })
    );
    setTogglePending((p) => ({ ...p, [id]: true }));
    try {
      await agentApi.update(id, { is_active: checked });
    } catch (err: any) {
      // Roll back to the captured prior value (not just `!checked`).
      if (priorActive !== undefined) {
        const restored = priorActive;
        setAgents((prev) =>
          prev.map((a) => (a.id === id ? { ...a, is_active: restored } : a))
        );
      }
      // Surface backend detail when available so users see the real reason.
      const detail = err?.response?.data?.detail;
      message.error(detail ? `状态切换失败:${detail}` : "状态切换失败");
    } finally {
      // Delete the key (not just set false) to prevent accumulation across
      // many toggles.
      setTogglePending((p) => {
        const next = { ...p };
        delete next[id];
        return next;
      });
    }
  };

  const openChat = (agent: Agent) => {
    setSelectedAgent(agent);
    setChatModalVisible(true);
    setMessages([]);
    setChatHistory([]);
    // Reset so the backend auto-creates a fresh Conversation for this
    // chat session; the returned id gets stashed on first response.
    setConversationId(null);
  };

  const sendMessage = async () => {
    if (!inputMessage.trim() || !selectedAgent) return;

    const userMessage: ChatMessage = { role: "user", content: inputMessage };
    setMessages((prev) => [...prev, userMessage]);
    setChatHistory((prev) => [...prev, userMessage]);
    setInputMessage("");
    setSending(true);

    try {
      const response = await agentApi.chat(
        selectedAgent.id,
        inputMessage,
        chatHistory,
        conversationId ?? undefined
      );
      if (process.env.NODE_ENV === "development") {
        console.log("Chat response:", response);
      }
      if (response.data.code === 200 && response.data.data?.response) {
        const assistantMessage: ChatMessage = {
          role: "assistant",
          content: response.data.data.response,
        };
        setMessages((prev) => [...prev, assistantMessage]);
        setChatHistory((prev) => [...prev, assistantMessage]);
        // Capture the persisted conversation id on first turn; reuse
        // for subsequent turns so all messages land in the same row.
        if (response.data.data.conversation_id && conversationId == null) {
          setConversationId(response.data.data.conversation_id);
        }
      } else {
        message.error(response.data.detail || "发送失败");
      }
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || "发送失败");
    } finally {
      setSending(false);
    }
  };

  const columns: ColumnsType<Agent> = [
    {
      title: "ID",
      dataIndex: "id",
      key: "id",
    },
    {
      title: "名称",
      dataIndex: "name",
      key: "name",
    },
    {
      title: "知识库",
      key: "knowledge_bases",
      render: (_, record: Agent) => <AgentKBBadge agent={record} />,
    },
    {
      title: "描述",
      dataIndex: "description",
      key: "description",
    },
    {
      title: "模型",
      dataIndex: "model_name",
      key: "model_name",
    },
    {
      title: "记忆策略",
      dataIndex: "memory_policy",
      key: "memory_policy",
      render: (v) => v || "sliding_window",
    },
    {
      title: "工具策略",
      dataIndex: "tool_choice",
      key: "tool_choice",
      render: (v) => v || "auto",
    },
    {
      title: "状态",
      dataIndex: "is_active",
      key: "is_active",
      render: (active: boolean, record: Agent) => (
        <Switch
          checked={active}
          loading={!!togglePending[record.id]}
          onChange={(checked) => handleToggleActive(record.id, checked)}
        />
      ),
    },
    {
      title: "操作",
      key: "action",
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => openChat(record)}>
            对话
          </Button>
          <Button size="small" onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Popconfirm
            title="确认删除?"
            onConfirm={() => handleDelete(record.id)}
          >
            <Button size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 16 }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setCreateOpen(true)}
        >
          创建Agent
        </Button>
      </div>
      <Table
        columns={columns}
        dataSource={agents}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />

      <AgentFormModal
        open={createOpen}
        mode="create"
        modelConfigs={modelConfigs}
        onCancel={() => setCreateOpen(false)}
        onSubmitted={handleCreated}
      />

      <AgentFormModal
        open={editOpen}
        mode="edit"
        initialValues={editingAgent ?? undefined}
        modelConfigs={modelConfigs}
        onCancel={() => setEditOpen(false)}
        onSubmitted={handleEdited}
      />

      <Modal
        title={`与 ${selectedAgent?.name} 对话`}
        open={chatModalVisible}
        onCancel={() => setChatModalVisible(false)}
        footer={null}
        width={700}
      >
        <Card
          style={{ height: 400, overflow: "auto", marginBottom: 16 }}
          styles={{ body: { padding: 16 } }}
        >
          <List
            dataSource={messages}
            renderItem={(msg) => (
              <List.Item
                style={{
                  display: "flex",
                  justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
                }}
              >
                <Space align="start">
                  {msg.role === "assistant" && (
                    <Avatar icon={<RobotOutlined />} style={{ backgroundColor: "#1890ff" }} />
                  )}
                  <Card
                    size="small"
                    style={{
                      maxWidth: "70%",
                      backgroundColor: msg.role === "user" ? "#1890ff" : "#f5f5f5",
                      color: msg.role === "user" ? "#fff" : "#000",
                    }}
                  >
                    {msg.role === "assistant" ? (
                      // Render LLM markdown response (titles, lists, tables,
                      // code blocks, etc.) instead of dumping the raw text.
                      // User messages stay plain — they're typically plain
                      // questions and need the blue-on-white bubble styling.
                      <Markdown content={msg.content} />
                    ) : (
                      msg.content
                    )}
                  </Card>
                  {msg.role === "user" && (
                    <Avatar icon={<UserOutlined />} style={{ backgroundColor: "#52c41a" }} />
                  )}
                </Space>
              </List.Item>
            )}
          />
        </Card>
        <Space.Compact style={{ width: "100%" }}>
          <Input
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            onPressEnter={sendMessage}
            placeholder="输入消息..."
            disabled={sending}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={sendMessage}
            loading={sending}
          >
            发送
          </Button>
        </Space.Compact>
      </Modal>
    </div>
  );
}
