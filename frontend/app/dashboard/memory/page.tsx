"use client";

import { useState, useEffect, useMemo } from "react";
import {
  Card,
  List,
  Input,
  Button,
  Space,
  Tag,
  Empty,
  message,
  Spin,
  Popconfirm,
  Row,
  Col,
  Segmented,
} from "antd";
import {
  SearchOutlined,
  DeleteOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { chatApi } from "@/services/chat";
import { memoryApi, MemoryMessage } from "@/services/memory";
import type { Conversation } from "@/types/chat";

const { TextArea } = Input;

export default function MemoryPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<number | null>(null);
  const [memoryMessages, setMemoryMessages] = useState<MemoryMessage[]>([]);
  const [globalContext, setGlobalContext] = useState<MemoryMessage[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [loadingGlobalContext, setLoadingGlobalContext] = useState(false);
  // M15: "all" shows every global memory row; "other" filters out the
  // currently selected conversation so the user can see what other
  // sessions contributed to the agent's long-term context.
  const [globalViewMode, setGlobalViewMode] = useState<"all" | "other">("all");

  // Derived list of global-memory rows the user should see right now.
  // In "other" mode, rows from the currently selected conv are dropped;
  // in "all" mode every row passes through (the dim styling on the
  // matching `List.Item` is the visual signal for "this is from the
  // conv you're looking at"). NULL `conversation_id` (legacy rows) is
  // always shown — we don't know which conv it came from.
  const visibleGlobal = useMemo(() => {
    if (globalViewMode === "other" && selectedConversationId != null) {
      return globalContext.filter(
        (m) => m.conversation_id !== selectedConversationId,
      );
    }
    return globalContext;
  }, [globalContext, globalViewMode, selectedConversationId]);

  // Fetch conversations on mount
  useEffect(() => {
    fetchConversations();
    fetchGlobalContext();
  }, []);

  // Fetch memory when conversation is selected
  useEffect(() => {
    if (selectedConversationId) {
      fetchMemoryHistory(selectedConversationId);
    }
  }, [selectedConversationId]);

  const fetchConversations = async () => {
    setLoadingConversations(true);
    try {
      const response = await chatApi.listConversations();
      if (response.data.code === 200) {
        setConversations(response.data.data || []);
      }
    } catch (error) {
      message.error("获取会话列表失败");
    } finally {
      setLoadingConversations(false);
    }
  };

  const fetchGlobalContext = async () => {
    setLoadingGlobalContext(true);
    try {
      const response = await memoryApi.getGlobalContext();
      if (response.data.code === 200) {
        setGlobalContext(response.data.data || []);
      }
    } catch (error) {
      message.error("获取全局上下文失败");
    } finally {
      setLoadingGlobalContext(false);
    }
  };

  const fetchMemoryHistory = async (conversationId: number) => {
    setLoading(true);
    try {
      const response = await memoryApi.getHistory(conversationId);
      if (response.data.code === 200) {
        setMemoryMessages(response.data.data || []);
      }
    } catch (error) {
      message.error("获取记忆历史失败");
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = async () => {
    if (!selectedConversationId) {
      return;
    }
    if (!searchQuery.trim()) {
      fetchMemoryHistory(selectedConversationId);
      return;
    }
    setLoading(true);
    try {
      const response = await memoryApi.searchMemory(selectedConversationId, searchQuery);
      if (response.data.code === 200) {
        setMemoryMessages(response.data.data || []);
      }
    } catch (error) {
      message.error("搜索记忆失败");
    } finally {
      setLoading(false);
    }
  };

  const handleClearMemory = async () => {
    if (!selectedConversationId) return;
    setLoading(true);
    try {
      const response = await memoryApi.clearMemory(selectedConversationId);
      if (response.data.code === 200) {
        message.success("记忆已清除");
        fetchMemoryHistory(selectedConversationId);
      }
    } catch (error) {
      message.error("清除记忆失败");
    } finally {
      setLoading(false);
    }
  };

  const getRoleTagColor = (role: string) => {
    switch (role) {
      case "user":
        return "blue";
      case "assistant":
        return "green";
      case "system":
        return "orange";
      default:
        return "default";
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Row gutter={16} style={{ height: "calc(100vh - 120px)" }}>
        {/* Left sidebar - Conversation list */}
        <Col span={6} style={{ height: "100%" }}>
          <Card
            title="会话列表"
            extra={<Button icon={<ReloadOutlined />} size="small" onClick={fetchConversations} />}
            // M38: Card 改 flex 容器,body 用 flex:1 + minHeight:0 才能让 overflow:auto
            // 真正触发滚动(默认 body 跟内容一起长,auto 形同虚设,146 条会话挤成一坨)
            style={{ height: "100%", display: "flex", flexDirection: "column" }}
            styles={{
              body: {
                padding: 0,
                overflow: "auto",
                flex: 1,
                minHeight: 0,
              },
            }}
          >
            <List
              loading={loadingConversations}
              dataSource={conversations}
              locale={{ emptyText: "暂无会话" }}
              renderItem={(item) => (
                <List.Item
                  key={item.id}
                  style={{
                    padding: "12px 16px",
                    cursor: "pointer",
                    backgroundColor:
                      selectedConversationId === item.id ? "#f0f5ff" : "transparent",
                  }}
                  onClick={() => setSelectedConversationId(item.id)}
                  // P0-6 (2026-06-20): 加删除按钮, 让用户能清理测试残留会话
                  // (e.g. dev DB 287 个 hello team 重复会话). Popconfirm 二次确认.
                  actions={[
                    <Popconfirm
                      key="del"
                      title="删除会话"
                      description="将删除该会话及其所有消息,不可恢复"
                      onConfirm={async (e) => {
                        e?.stopPropagation();
                        try {
                          await chatApi.deleteConversation(item.id);
                          message.success("已删除");
                          if (selectedConversationId === item.id) {
                            setSelectedConversationId(null);
                          }
                          fetchConversations();
                        } catch (err) {
                          message.error("删除失败");
                        }
                      }}
                      onCancel={(e) => e?.stopPropagation()}
                      okText="删除"
                      cancelText="取消"
                    >
                      <Button
                        type="text"
                        danger
                        size="small"
                        icon={<DeleteOutlined />}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </Popconfirm>,
                  ]}
                >
                  <List.Item.Meta
                    title={item.title || `会话 #${item.id}`}
                    description={new Date(item.updated_at).toLocaleString()}
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>

        {/* Right side - Memory content */}
        <Col span={18} style={{ height: "100%", display: "flex", flexDirection: "column" }}>
          {/* Global Context Card */}
          <Card
            title="全局上下文"
            extra={
              <Space>
                <Segmented
                  value={globalViewMode}
                  onChange={(v) => setGlobalViewMode(v as "all" | "other")}
                  options={[
                    { label: "全部", value: "all" },
                    { label: "只看其它会话", value: "other" },
                  ]}
                />
                <Button
                  icon={<ReloadOutlined />}
                  size="small"
                  onClick={fetchGlobalContext}
                  loading={loadingGlobalContext}
                >
                  刷新
                </Button>
              </Space>
            }
            style={{ marginBottom: 16 }}
          >
            {loadingGlobalContext ? (
              <Spin size="small" />
            ) : visibleGlobal.length > 0 ? (
              <List
                dataSource={visibleGlobal}
                renderItem={(item, index) => {
                  // M15: dim rows from the currently selected conv so
                  // the user can visually tell them apart from rows
                  // that came from other conversations. NULL
                  // `conversation_id` (legacy rows) is never dimmed.
                  const isCurrent =
                    selectedConversationId != null &&
                    item.conversation_id === selectedConversationId;
                  return (
                    <List.Item
                      key={index}
                      style={{
                        alignItems: "flex-start",
                        opacity: isCurrent ? 0.45 : 1,
                      }}
                    >
                      <List.Item.Meta
                        avatar={
                          <Tag color={getRoleTagColor(item.role)}>
                            {item.role === "user"
                              ? "用户"
                              : item.role === "assistant"
                              ? "助手"
                              : "系统"}
                          </Tag>
                        }
                        title={item.role}
                        description={
                          <div style={{ marginTop: 8 }}>
                            <TextArea
                              value={item.content}
                              readOnly
                              autoSize
                              style={{
                                background: "transparent",
                                border: "none",
                                resize: "none",
                              }}
                            />
                          </div>
                        }
                      />
                    </List.Item>
                  );
                }}
                style={{ maxHeight: 300, overflow: "auto" }}
              />
            ) : (
              <Empty
                description={
                  globalViewMode === "other"
                    ? "其它会话暂无记忆"
                    : "暂无全局上下文"
                }
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            )}
          </Card>

          {/* Memory History Card */}
          <Card
            title={selectedConversationId ? `记忆历史 - 会话 #${selectedConversationId}` : "记忆历史"}
            style={{ flex: 1, display: "flex", flexDirection: "column" }}
            styles={{ body: { flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" } }}
            extra={
              <Space>
                <Input
                  placeholder="搜索记忆..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onPressEnter={handleSearch}
                  style={{ width: 200 }}
                  prefix={<SearchOutlined />}
                />
                <Button onClick={handleSearch}>搜索</Button>
                <Popconfirm
                  title="确认清除此会话的记忆?"
                  onConfirm={handleClearMemory}
                  okText="确认"
                  cancelText="取消"
                  disabled={!selectedConversationId}
                >
                  <Button
                    danger
                    icon={<DeleteOutlined />}
                    disabled={!selectedConversationId}
                  >
                    清除记忆
                  </Button>
                </Popconfirm>
              </Space>
            }
          >
            {!selectedConversationId ? (
              <Empty description="请先选择一个会话" />
            ) : loading ? (
              <div style={{ textAlign: "center", padding: 40 }}>
                <Spin size="large" />
              </div>
            ) : memoryMessages.length === 0 ? (
              <Empty description="暂无记忆" />
            ) : (
              <div style={{ overflow: "auto", flex: 1 }}>
                <List
                  dataSource={memoryMessages}
                  renderItem={(item, index) => (
                    <List.Item key={index} style={{ alignItems: "flex-start" }}>
                      <List.Item.Meta
                        avatar={
                          <Tag color={getRoleTagColor(item.role)}>
                            {item.role === "user"
                              ? "用户"
                              : item.role === "assistant"
                              ? "助手"
                              : "系统"}
                          </Tag>
                        }
                        title={item.role}
                        description={
                          <div style={{ marginTop: 8 }}>
                            <TextArea
                              value={item.content}
                              readOnly
                              autoSize
                              style={{
                                background: "transparent",
                                border: "none",
                                resize: "none",
                              }}
                            />
                            {item.metadata && typeof item.metadata === 'object' && Object.keys(item.metadata).length > 0 && (
                              <div style={{ marginTop: 8, fontSize: 12, color: "#999" }}>
                                {JSON.stringify(item.metadata)}
                              </div>
                            )}
                          </div>
                        }
                      />
                    </List.Item>
                  )}
                />
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
