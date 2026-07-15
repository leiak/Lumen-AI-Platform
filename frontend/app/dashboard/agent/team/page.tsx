"use client";

import { useEffect, useState } from "react";
import {
  Table,
  Button,
  Space,
  Modal,
  Form,
  Input,
  Select,
  message,
  Popconfirm,
  Card,
  Avatar,
  List,
  Tag,
  Tabs,
  Empty,
  Spin,
  Tooltip,
} from "antd";
import {
  PlusOutlined,
  SendOutlined,
  RobotOutlined,
  UserOutlined,
  TeamOutlined,
  DeleteOutlined,
  MessageOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import {
  agentTeamApi,
  AgentTeam,
  AgentTeamSummary,
  RoutePolicy,
  TeamChatResponse,
  TeamConversation,
  TeamMessage,
  TeamMessageMetadata,
  WorkerOutput,
} from "@/services/agentTeam";
import { agentApi } from "@/services/agent";
import type { Agent } from "@/types/api";
import { AgentKBBanner } from "@/components/agent/AgentKBBanner";

const { TextArea } = Input;

const ROUTE_POLICY_OPTIONS: { value: RoutePolicy; label: string }[] = [
  { value: "manager_decides", label: "Manager decides" },
  { value: "round_robin", label: "Round robin" },
  { value: "first_match", label: "First match (keyword)" },
];

/**
 * Convert DB messages loaded via `getMessages` into the in-memory
 * `chatMessages` shape used by the chat list. The assistant message's
 * `metadata` JSON is unpacked into a fake `TeamChatResponse` so the
 * existing folding region (`worker_outputs` / `manager_reasoning` /
 * `routing_decision` / `policy_used`) renders for historical turns
 * without a second round-trip.
 */
function convertDbMessagesToChat(
  msgs: TeamMessage[],
): Array<{ role: "user" | "assistant"; content: string; team?: TeamChatResponse }> {
  return msgs
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => {
      if (m.role === "assistant") {
        const meta = (m.metadata || {}) as TeamMessageMetadata;
        return {
          role: "assistant" as const,
          content: m.content,
          team: {
            final_answer: m.content,
            manager_reasoning: meta.manager_reasoning ?? null,
            routing_decision: meta.routing_decision ?? null,
            worker_outputs: (meta.worker_outputs as WorkerOutput[]) || [],
            policy_used: (meta.policy_used as RoutePolicy) || "manager_decides",
            team_id: 0,
            conversation_id: m.conversation_id,
          },
        };
      }
      return { role: "user" as const, content: m.content };
    });
}

export default function AgentTeamPage() {
  const [teams, setTeams] = useState<AgentTeamSummary[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(false);
  // Server-side pagination state (see agent/page.tsx for the same
  // rationale — the Table was previously stuck on the first page).
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [total, setTotal] = useState(0);

  // Create modal
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm();

  // Detail / edit modal
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailTeam, setDetailTeam] = useState<AgentTeam | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Add-member sub-modal
  const [addMemberOpen, setAddMemberOpen] = useState(false);
  const [addMemberForm] = Form.useForm();

  // Chat modal
  const [chatOpen, setChatOpen] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<
    Array<{ role: "user" | "assistant"; content: string; team?: TeamChatResponse }>
  >([]);
  const [chatSending, setChatSending] = useState(false);
  // Conversation history sidebar. `currentConvId === null` means
  // "no conversation selected — backend will create a new one on the
  // first send". After the first send the response carries the
  // newly-created conversation_id and we patch it back here.
  const [teamConvs, setTeamConvs] = useState<TeamConversation[]>([]);
  const [currentConvId, setCurrentConvId] = useState<number | null>(null);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [deletingConvId, setDeletingConvId] = useState<number | null>(null);

  const fetchTeams = async () => {
    setLoading(true);
    try {
      const res = await agentTeamApi.list(page, pageSize);
      if (res.data.code === 200) {
        setTeams(res.data.data || []);
        setTotal(res.data.total || 0);
      }
    } catch (err) {
      message.error("获取团队列表失败");
    } finally {
      setLoading(false);
    }
  };

  const fetchAgents = async () => {
    try {
      const res = await agentApi.list(1, 100);
      if (res.data.code === 200) {
        setAgents(res.data.data || []);
      }
    } catch (err) {
      message.error("加载 Agent 列表失败");
    }
  };

  useEffect(() => {
    fetchTeams();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize]);

  useEffect(() => {
    fetchAgents();
  }, []);

  const openDetail = async (id: number) => {
    setDetailOpen(true);
    setDetailLoading(true);
    try {
      const res = await agentTeamApi.get(id);
      if (res.data.code === 200) {
        setDetailTeam(res.data.data || null);
      } else {
        setDetailTeam(null);
      }
    } catch (err) {
      message.error("加载团队详情失败");
      setDetailOpen(false);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleCreate = async (values: any) => {
    // P0-5 (2026-06-20): 前端先校验至少 1 个 member, 后端 Pydantic
    // min_length=1 兜底 (避免 dev DB 累积 0-member orphan team)
    if (!values.members || values.members.length === 0) {
      message.error("请至少添加 1 个 Worker 成员");
      return;
    }
    try {
      const res = await agentTeamApi.create({
        name: values.name,
        description: values.description,
        manager_agent_id: values.manager_agent_id,
        route_policy: values.route_policy,
        aggregator_prompt: values.aggregator_prompt,
        is_active: true,
        members: (values.members || []).map((m: any) => ({
          agent_id: m.agent_id,
          role: m.role,
          priority: m.priority ?? 100,
          is_active: true,
        })),
      });
      if (res.data.code === 200) {
        message.success("创建成功");
        setCreateOpen(false);
        createForm.resetFields();
        fetchTeams();
      } else {
        message.error(res.data.message || "创建失败");
      }
    } catch (err: any) {
      message.error(err?.response?.data?.detail || "创建失败");
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await agentTeamApi.remove(id);
      message.success("删除成功");
      fetchTeams();
    } catch (err) {
      message.error("删除失败");
    }
  };

  const handleAddMember = async (values: any) => {
    if (!detailTeam) return;
    try {
      const res = await agentTeamApi.addMember(detailTeam.id, {
        agent_id: values.agent_id,
        role: values.role,
        priority: values.priority ?? 100,
        is_active: true,
      });
      if (res.data.code === 200) {
        message.success("已添加成员");
        setAddMemberOpen(false);
        addMemberForm.resetFields();
        openDetail(detailTeam.id);
      } else {
        message.error(res.data.message || "添加失败");
      }
    } catch (err: any) {
      message.error(err?.response?.data?.detail || "添加失败");
    }
  };

  const handleRemoveMember = async (memberId: number) => {
    if (!detailTeam) return;
    try {
      await agentTeamApi.removeMember(detailTeam.id, memberId);
      message.success("已移除成员");
      openDetail(detailTeam.id);
    } catch (err) {
      message.error("移除失败");
    }
  };

  const openChat = async (team: AgentTeamSummary) => {
    // Open chat with the lightweight summary; the chat API only needs the id.
    setChatOpen(true);
    setChatMessages([]);
    setChatInput("");
    setCurrentConvId(null);
    // Keep a tiny stub for the team context
    setDetailTeam({
      ...({} as AgentTeam),
      id: team.id,
      name: team.name,
      description: team.description,
      manager_agent_id: team.manager_agent_id,
      is_active: team.is_active,
      route_policy: team.route_policy,
      aggregator_prompt: team.aggregator_prompt,
      config: team.config,
      tenant_id: team.tenant_id,
      created_at: team.created_at,
      members: [],
      routes: [],
    });
    // Load existing team conversations and auto-select the most recent.
    // Failures here are non-fatal — the user can still send the first
    // message and the backend will create a new conversation on demand.
    try {
      const res = await agentTeamApi.listConversations(team.id);
      if (res.data.code === 200) {
        const list = res.data.data || [];
        setTeamConvs(list);
        if (list.length > 0) {
          setCurrentConvId(list[0].id);
        }
      } else {
        setTeamConvs([]);
      }
    } catch (err) {
      message.error("加载 Team 对话列表失败");
      setTeamConvs([]);
    }
  };

  // Load the full message thread whenever the user switches to a
  // different conversation (or selects one for the first time). Driven
  // by an effect rather than an inline await so React state updates
  // stay consistent across rapid clicks.
  useEffect(() => {
    if (!detailTeam || currentConvId === null) {
      return;
    }
    let cancelled = false;
    setLoadingMessages(true);
    (async () => {
      try {
        const res = await agentTeamApi.getMessages(detailTeam.id, currentConvId);
        if (cancelled) return;
        if (res.data.code === 200) {
          setChatMessages(convertDbMessagesToChat(res.data.data || []));
        }
      } catch (err) {
        if (cancelled) return;
        message.error("加载历史消息失败");
      } finally {
        if (!cancelled) setLoadingMessages(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentConvId, detailTeam]);

  const handleNewTeamConversation = async () => {
    if (!detailTeam) return;
    try {
      const res = await agentTeamApi.createConversation(detailTeam.id);
      if (res.data.code === 200) {
        const conv = res.data.data as TeamConversation;
        setTeamConvs([conv, ...teamConvs]);
        setCurrentConvId(conv.id);
        setChatMessages([]);
      } else {
        message.error(res.data.message || "新建对话失败");
      }
    } catch (err) {
      message.error("新建对话失败");
    }
  };

  const handleDeleteTeamConversation = async (convId: number) => {
    if (!detailTeam) return;
    setDeletingConvId(convId);
    try {
      const res = await agentTeamApi.deleteConversation(detailTeam.id, convId);
      if (res.data.code === 200) {
        message.success("已删除");
        // Remove from local list. If we just deleted the current one,
        // jump to the next conversation (or null if none remain) so the
        // chat area doesn't keep showing a soft-deleted thread.
        const remaining = teamConvs.filter((c) => c.id !== convId);
        setTeamConvs(remaining);
        if (currentConvId === convId) {
          setCurrentConvId(remaining[0]?.id ?? null);
          setChatMessages([]);
        }
      } else {
        message.error(res.data.message || "删除失败");
      }
    } catch (err) {
      message.error("删除失败");
    } finally {
      setDeletingConvId(null);
    }
  };

  // Helper: refresh the sidebar (called after sending a message so the
  // new conversation shows up immediately, or its title gets bumped).
  const refreshTeamConvs = async () => {
    if (!detailTeam) return;
    try {
      const res = await agentTeamApi.listConversations(detailTeam.id);
      if (res.data.code === 200) {
        setTeamConvs(res.data.data || []);
      }
    } catch (err) {
      message.error("刷新 Team 对话列表失败");
    }
  };

  const sendTeamMessage = async () => {
    if (!chatInput.trim() || !detailTeam) return;
    const userMsg = { role: "user" as const, content: chatInput };
    setChatMessages((prev) => [...prev, userMsg]);
    const sent = chatInput;
    setChatInput("");
    setChatSending(true);
    try {
      const res = await agentTeamApi.chat(
        detailTeam.id,
        sent,
        currentConvId ?? undefined,
      );
      if (res.data.code === 200) {
        const data = res.data.data as TeamChatResponse;
        setChatMessages((prev) => [
          ...prev,
          { role: "assistant", content: data.final_answer, team: data },
        ]);
        // First send on a fresh modal creates the conv server-side;
        // patch the id back so subsequent turns reuse it and the
        // sidebar shows the new entry.
        if (currentConvId === null && data.conversation_id) {
          setCurrentConvId(data.conversation_id);
        }
        refreshTeamConvs();
      } else {
        message.error(res.data.message || "团队对话失败");
      }
    } catch (err: any) {
      message.error(err?.response?.data?.detail || "团队对话失败");
    } finally {
      setChatSending(false);
    }
  };

  const columns: ColumnsType<AgentTeamSummary> = [
    { title: "ID", dataIndex: "id", key: "id", width: 60 },
    { title: "名称", dataIndex: "name", key: "name" },
    {
      title: "描述",
      dataIndex: "description",
      key: "description",
      ellipsis: true,
    },
    {
      title: "Manager Agent",
      // P0-4 (2026-06-20): 后端 outer-join agents.name, 这里显示名称,
      // fallback 到 "#<id>" 应对 agent 被删/corrupt 情况
      dataIndex: "manager_agent_name",
      key: "manager_agent_name",
      width: 180,
      render: (name: string | null, record: AgentTeamSummary) =>
        name ?? `#${record.manager_agent_id}`,
    },
    {
      title: "策略",
      dataIndex: "route_policy",
      key: "route_policy",
      width: 140,
      render: (p: RoutePolicy) => <Tag color="blue">{p}</Tag>,
    },
    {
      title: "成员数",
      dataIndex: "member_count",
      key: "member_count",
      width: 90,
    },
    {
      title: "状态",
      dataIndex: "is_active",
      key: "is_active",
      width: 80,
      render: (a) => (a ? "启用" : "禁用"),
    },
    {
      title: "操作",
      key: "action",
      width: 280,
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => openChat(record)}>
            对话
          </Button>
          <Button size="small" onClick={() => openDetail(record.id)}>
            管理
          </Button>
          <Popconfirm title="确认删除?" onConfirm={() => handleDelete(record.id)}>
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
      <Card
        title={
          <Space>
            <TeamOutlined />
            <span>多代理团队 (Multi-Agent)</span>
          </Space>
        }
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              if (agents.length === 0) {
                message.warning("请先创建至少一个 Agent");
                return;
              }
              setCreateOpen(true);
            }}
          >
            创建团队
          </Button>
        }
      >
        <Table
          columns={columns}
          dataSource={teams}
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
      </Card>

      {/* Create modal */}
      <Modal
        title="创建多代理团队"
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false);
          createForm.resetFields();
        }}
        footer={null}
        width={700}
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={handleCreate}
          initialValues={{ route_policy: "manager_decides", members: [] }}
        >
          <Form.Item
            name="name"
            label="团队名称"
            rules={[{ required: true, message: "请输入团队名称" }]}
          >
            <Input placeholder="如: 客服三人组" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <TextArea rows={2} placeholder="团队用途描述" />
          </Form.Item>
          <Form.Item
            name="manager_agent_id"
            label="Manager Agent"
            rules={[{ required: true, message: "请选择 Manager Agent" }]}
          >
            <Select placeholder="选择负责调度与汇总的 Agent" showSearch optionFilterProp="children">
              {agents.map((a) => (
                <Select.Option key={a.id} value={a.id}>
                  {a.name} (#{a.id})
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="route_policy" label="路由策略">
            <Select options={ROUTE_POLICY_OPTIONS} />
          </Form.Item>
          <Form.Item name="aggregator_prompt" label="汇总 Prompt (可选)">
            <TextArea
              rows={3}
              placeholder="留空则使用 Manager Agent 自身进行汇总。模板中可使用 {workers} {user_message} {answers} 占位符。"
            />
          </Form.Item>
          <Form.List name="members">
            {(fields, { add, remove }) => (
              <>
                <div style={{ marginBottom: 8, fontWeight: 500 }}>Worker 成员</div>
                {fields.map((field) => (
                  <Space
                    key={field.key}
                    align="baseline"
                    style={{ display: "flex", marginBottom: 8 }}
                  >
                    <Form.Item
                      name={[field.name, "agent_id"]}
                      rules={[{ required: true, message: "请选择 Agent" }]}
                    >
                      <Select
                        placeholder="Worker Agent"
                        style={{ width: 220 }}
                        showSearch
                        optionFilterProp="children"
                      >
                        {agents.map((a) => (
                          <Select.Option key={a.id} value={a.id}>
                            {a.name} (#{a.id})
                          </Select.Option>
                        ))}
                      </Select>
                    </Form.Item>
                    <Form.Item name={[field.name, "role"]} initialValue="worker">
                      <Input placeholder="角色" style={{ width: 140 }} />
                    </Form.Item>
                    <Form.Item name={[field.name, "priority"]} initialValue={100}>
                      <Input type="number" placeholder="优先级" style={{ width: 100 }} />
                    </Form.Item>
                    <Button danger onClick={() => remove(field.name)} icon={<DeleteOutlined />} />
                  </Space>
                ))}
                <Button type="dashed" onClick={() => add()} block icon={<PlusOutlined />}>
                  添加 Worker
                </Button>
              </>
            )}
          </Form.List>
          <Form.Item style={{ marginTop: 16 }}>
            <Space>
              <Button type="primary" htmlType="submit">
                创建
              </Button>
              <Button onClick={() => setCreateOpen(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* Detail / manage modal */}
      <Modal
        title={detailTeam ? `团队详情: ${detailTeam.name}` : "团队详情"}
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={null}
        width={800}
      >
        {detailLoading ? (
          <div style={{ textAlign: "center", padding: 48 }}>
            <Spin />
          </div>
        ) : detailTeam ? (
          <Tabs
            items={[
              {
                key: "info",
                label: "基本信息",
                children: (
                  <Space direction="vertical" style={{ width: "100%" }}>
                    <div>
                      <b>描述：</b>
                      {detailTeam.description || "无"}
                    </div>
                    <div>
                      <b>Manager Agent ID：</b>
                      {detailTeam.manager_agent_id}
                    </div>
                    <div>
                      <b>路由策略：</b>
                      <Tag color="blue">{detailTeam.route_policy}</Tag>
                    </div>
                    <div>
                      <b>状态：</b>
                      {detailTeam.is_active ? "启用" : "禁用"}
                    </div>
                    <div>
                      <b>创建时间：</b>
                      {detailTeam.created_at}
                    </div>
                  </Space>
                ),
              },
              {
                key: "members",
                label: `成员 (${detailTeam.members?.length || 0})`,
                children: (
                  <Space direction="vertical" style={{ width: "100%" }}>
                    <Button
                      type="dashed"
                      icon={<PlusOutlined />}
                      onClick={() => setAddMemberOpen(true)}
                    >
                      添加成员
                    </Button>
                    {(!detailTeam.members || detailTeam.members.length === 0) ? (
                      <Empty description="暂无成员" />
                    ) : (
                      <List
                        dataSource={detailTeam.members}
                        renderItem={(m) => (
                          <List.Item
                            actions={[
                              <Popconfirm
                                key="del"
                                title="移除该成员?"
                                onConfirm={() => handleRemoveMember(m.id)}
                              >
                                <Button size="small" danger>
                                  移除
                                </Button>
                              </Popconfirm>,
                            ]}
                          >
                            <List.Item.Meta
                              avatar={<Avatar icon={<RobotOutlined />} />}
                              title={
                                <Space>
                                  <span>
                                    {m.agent_name || `Agent #${m.agent_id}`}
                                  </span>
                                  <Tag>{m.role}</Tag>
                                  <Tag color="purple">priority={m.priority}</Tag>
                                </Space>
                              }
                              description={`member_id=${m.id} agent_id=${m.agent_id}`}
                            />
                          </List.Item>
                        )}
                      />
                    )}
                  </Space>
                ),
              },
            ]}
          />
        ) : (
          <Empty description="未找到团队" />
        )}
      </Modal>

      {/* Add member modal */}
      <Modal
        title="添加 Worker 成员"
        open={addMemberOpen}
        onCancel={() => setAddMemberOpen(false)}
        footer={null}
      >
        <Form
          form={addMemberForm}
          layout="vertical"
          onFinish={handleAddMember}
          initialValues={{ role: "worker", priority: 100 }}
        >
          <Form.Item
            name="agent_id"
            label="Worker Agent"
            rules={[{ required: true, message: "请选择 Worker Agent" }]}
          >
            <Select placeholder="选择 Agent" showSearch optionFilterProp="children">
              {agents.map((a) => (
                <Select.Option key={a.id} value={a.id}>
                  {a.name} (#{a.id})
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="role" label="角色">
            <Input placeholder="worker / researcher / writer ..." />
          </Form.Item>
          <Form.Item name="priority" label="优先级">
            <Input type="number" min={0} />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                添加
              </Button>
              <Button onClick={() => setAddMemberOpen(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* Chat modal */}
      <Modal
        title={`与团队 ${detailTeam?.name || ""} 对话`}
        open={chatOpen}
        onCancel={() => setChatOpen(false)}
        footer={null}
        width={1000}
        styles={{ body: { padding: 0 } }}
      >
        <div style={{ display: "flex", height: 560 }}>
          {/* Sidebar — team conversation list */}
          <div
            style={{
              width: 260,
              minWidth: 260,
              borderRight: "1px solid #f0f0f0",
              display: "flex",
              flexDirection: "column",
              background: "#fafafa",
            }}
          >
            <div style={{ padding: 12 }}>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                block
                onClick={handleNewTeamConversation}
              >
                新建对话
              </Button>
            </div>
            <div style={{ flex: 1, overflowY: "auto" }}>
              {teamConvs.length === 0 ? (
                <div
                  style={{
                    textAlign: "center",
                    color: "#999",
                    padding: "24px 12px",
                    fontSize: 12,
                  }}
                >
                  尚无历史对话
                </div>
              ) : (
                <List
                  dataSource={teamConvs}
                  renderItem={(item) => (
                    <List.Item
                      key={item.id}
                      onClick={() => setCurrentConvId(item.id)}
                      actions={[
                        <Popconfirm
                          key="delete"
                          title="删除该对话?"
                          okText="删除"
                          cancelText="取消"
                          okButtonProps={{ danger: true }}
                          onConfirm={(e) => {
                            e?.stopPropagation();
                            handleDeleteTeamConversation(item.id);
                          }}
                          onCancel={(e) => e?.stopPropagation()}
                        >
                          <Button
                            type="text"
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            loading={deletingConvId === item.id}
                            aria-label="删除"
                            onClick={(e) => e.stopPropagation()}
                          />
                        </Popconfirm>,
                      ]}
                      style={{
                        cursor: "pointer",
                        background:
                          currentConvId === item.id ? "#e6f7ff" : "transparent",
                        padding: "10px 12px",
                        borderBottom: "1px solid #f0f0f0",
                      }}
                    >
                      <List.Item.Meta
                        avatar={
                          <MessageOutlined
                            style={{
                              color:
                                currentConvId === item.id ? "#1890ff" : "#999",
                            }}
                          />
                        }
                        title={
                          <Tooltip
                            title={item.title || "新对话"}
                            placement="topLeft"
                          >
                            <span
                              style={{
                                display: "inline-block",
                                maxWidth: 170,
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                                verticalAlign: "bottom",
                              }}
                            >
                              {item.title || "新对话"}
                            </span>
                          </Tooltip>
                        }
                        description={new Date(item.updated_at).toLocaleString()}
                      />
                    </List.Item>
                  )}
                />
              )}
            </div>
          </div>

          {/* Main chat area */}
          <div
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              minWidth: 0,
            }}
          >
            <Card
              style={{ flex: 1, overflow: "auto", marginBottom: 12 }}
              styles={{ body: { padding: 16 } }}
            >
              {(() => {
                // M21 T22: show the manager agent's KB binding banner above
                // the message list. The team summary only carries
                // `manager_agent_id` (an int), so we look the full Agent up
                // in the already-loaded `agents` list. AgentKBBanner
                // returns null when `knowledge_bases` is empty, so this is
                // a safe no-op for managers without KB bindings.
                const managerAgent = detailTeam
                  ? agents.find((a) => a.id === detailTeam.manager_agent_id)
                  : undefined;
                if (!managerAgent) return null;
                return <AgentKBBanner agent={managerAgent} />;
              })()}
              {loadingMessages ? (
                <div style={{ textAlign: "center", padding: 48 }}>
                  <Spin tip="加载历史消息..." />
                </div>
              ) : chatMessages.length === 0 ? (
                <Empty description="开始一轮团队协作吧" />
              ) : (
                <List
                  dataSource={chatMessages}
                  renderItem={(msg, idx) => (
                    <List.Item
                      key={idx}
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        alignItems:
                          msg.role === "user" ? "flex-end" : "flex-start",
                      }}
                    >
                      <Space align="start">
                        {msg.role === "assistant" && (
                          <Avatar
                            icon={<RobotOutlined />}
                            style={{ backgroundColor: "#722ed1" }}
                          />
                        )}
                        <Card
                          size="small"
                          style={{
                            maxWidth: "85%",
                            backgroundColor:
                              msg.role === "user" ? "#1890ff" : "#f5f5f5",
                            color: msg.role === "user" ? "#fff" : "#000",
                          }}
                        >
                          {msg.content}
                        </Card>
                        {msg.role === "user" && (
                          <Avatar
                            icon={<UserOutlined />}
                            style={{ backgroundColor: "#52c41a" }}
                          />
                        )}
                      </Space>
                      {msg.team && (
                        <div
                          style={{
                            marginTop: 6,
                            marginLeft: msg.role === "user" ? 0 : 44,
                            fontSize: 12,
                            color: "#888",
                            width: "100%",
                          }}
                        >
                          <div>
                            <b>策略：</b>
                            <Tag color="blue">{msg.team.policy_used}</Tag>
                            {msg.team.routing_decision?.length ? (
                              <Tag color="geekblue">
                                路由: {msg.team.routing_decision.join(", ")}
                              </Tag>
                            ) : null}
                          </div>
                          {msg.team.manager_reasoning && (
                            <div style={{ marginTop: 2 }}>
                              <b>Manager 思路：</b>
                              {msg.team.manager_reasoning}
                            </div>
                          )}
                          {msg.team.worker_outputs?.length > 0 && (
                            <div style={{ marginTop: 6 }}>
                              <b>Worker 输出：</b>
                              {msg.team.worker_outputs.map(
                                (wo: WorkerOutput, i) => (
                                  <Card
                                    key={i}
                                    size="small"
                                    style={{ marginTop: 4, background: "#fafafa" }}
                                  >
                                    <div style={{ fontSize: 12, color: "#555" }}>
                                      <Tag color="purple">
                                        {wo.role || "worker"}
                                      </Tag>
                                      {wo.agent_name || `agent#${wo.agent_id}`}
                                    </div>
                                    <div style={{ whiteSpace: "pre-wrap" }}>
                                      {wo.response}
                                    </div>
                                  </Card>
                                ),
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </List.Item>
                  )}
                />
              )}
            </Card>
            <Space.Compact style={{ width: "100%", padding: "0 12px 12px 0" }}>
              <Input
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onPressEnter={sendTeamMessage}
                placeholder="向团队提问..."
                disabled={chatSending}
              />
              <Button
                type="primary"
                icon={<SendOutlined />}
                onClick={sendTeamMessage}
                loading={chatSending}
              >
                发送
              </Button>
            </Space.Compact>
          </div>
        </div>
      </Modal>
    </div>
  );
}
