// frontend/app/dashboard/customer/[id]/page.tsx
// M33 — 客户详情页.
//
// Spec §5.3 — 3 列布局:左 8/24 基础/公司/属性/自定义/备注 + 系统信息,
// 右 16/24 跟进 timeline + AI 智能建议按钮.
"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Button,
  Card,
  DatePicker,
  Descriptions,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
  Timeline,
  App,
  Drawer,
  Collapse,
  Popconfirm,
} from "antd";
import {
  ArrowLeftOutlined,
  EditOutlined,
  RobotOutlined,
  PlusOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { customerApi } from "@/services/customer";
import type {
  AIAdvisorResponse,
  CustomerDetail,
  CustomerFieldDefinitionResponse,
  CustomerLevel,
  FollowUpResponse,
  FollowUpType,
} from "@/types/customer";

const LEVEL_COLORS: Record<string, string> = {
  vip: "gold",
  normal: "blue",
  potential: "cyan",
  lost: "default",
};
const LEVEL_LABELS: Record<string, string> = {
  vip: "VIP",
  normal: "普通",
  potential: "潜在",
  lost: "已流失",
};

const FOLLOW_UP_TYPE_LABELS: Record<FollowUpType, string> = {
  phone: "电话",
  wechat: "微信",
  email: "邮件",
  meeting: "会议",
  other: "其他",
};

const FOLLOW_UP_TYPE_COLORS: Record<FollowUpType, string> = {
  phone: "blue",
  wechat: "green",
  email: "purple",
  meeting: "magenta",
  other: "default",
};

export default function CustomerDetailPage() {
  const params = useParams<{ id: string }>();
  const customerId = Number(params?.id);
  const router = useRouter();
  const qc = useQueryClient();
  const { message: toast } = App.useApp();

  const [followUpOpen, setFollowUpOpen] = useState(false);
  const [editingFollowUp, setEditingFollowUp] = useState<FollowUpResponse | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiResult, setAiResult] = useState<AIAdvisorResponse | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiFocus, setAiFocus] = useState("");
  const [followUpForm] = Form.useForm();

  const { data: customer, isLoading } = useQuery({
    queryKey: ["customer", "detail", customerId],
    queryFn: () => customerApi.get(customerId),
    enabled: Number.isFinite(customerId) && customerId > 0,
  });

  const { data: followUps } = useQuery({
    queryKey: ["customer", "follow-ups", customerId],
    queryFn: () => customerApi.listFollowUps(customerId, 1, 100),
    enabled: Number.isFinite(customerId) && customerId > 0,
  });

  const handleAiSuggest = async () => {
    setAiOpen(true);
    setAiResult(null);
    setAiLoading(true);
    try {
      const result = await customerApi.aiSuggest(customerId, {
        focus: aiFocus || undefined,
      });
      setAiResult(result);
    } catch (err: any) {
      toast.error(err?.message || "AI 智能建议失败");
      setAiOpen(false);
    } finally {
      setAiLoading(false);
    }
  };

  const handleAdoptAiSuggestion = async () => {
    if (!aiResult) return;
    try {
      await customerApi.createFollowUp(customerId, {
        follow_up_type: "other",
        content: aiResult.suggested_message,
        next_follow_up_at: aiResult.suggested_next_follow_up_at ?? undefined,
      });
      toast.success("已采纳,跟进已创建");
      setAiOpen(false);
      setAiResult(null);
      setAiFocus("");
      qc.invalidateQueries({ queryKey: ["customer"] });
    } catch (err: any) {
      toast.error(err?.message || "采纳失败");
    }
  };

  const handleCreateFollowUp = async () => {
    const values = await followUpForm.validateFields();
    try {
      await customerApi.createFollowUp(customerId, {
        follow_up_type: values.follow_up_type,
        content: values.content,
        next_step: values.next_step,
        next_follow_up_at: values.next_follow_up_at
          ? values.next_follow_up_at.toISOString()
          : undefined,
      });
      toast.success("跟进已创建");
      setFollowUpOpen(false);
      followUpForm.resetFields();
      qc.invalidateQueries({ queryKey: ["customer"] });
    } catch (err: any) {
      if (err?.errorFields) return;
      toast.error(err?.message || "创建失败");
    }
  };

  const handleUpdateFollowUp = async () => {
    if (!editingFollowUp) return;
    const values = await followUpForm.validateFields();
    try {
      await customerApi.updateFollowUp(customerId, editingFollowUp.id, {
        follow_up_type: values.follow_up_type,
        content: values.content,
        next_step: values.next_step,
        next_follow_up_at: values.next_follow_up_at
          ? values.next_follow_up_at.toISOString()
          : undefined,
      });
      toast.success("跟进已更新");
      setEditingFollowUp(null);
      followUpForm.resetFields();
      qc.invalidateQueries({ queryKey: ["customer"] });
    } catch (err: any) {
      if (err?.errorFields) return;
      toast.error(err?.message || "更新失败");
    }
  };

  const handleDeleteFollowUp = async (followUpId: number) => {
    try {
      await customerApi.deleteFollowUp(customerId, followUpId);
      toast.success("跟进已删除");
      qc.invalidateQueries({ queryKey: ["customer"] });
    } catch (err: any) {
      toast.error(err?.message || "删除失败");
    }
  };

  const openCreateFollowUp = () => {
    setEditingFollowUp(null);
    followUpForm.resetFields();
    setFollowUpOpen(true);
  };

  const openEditFollowUp = (fu: FollowUpResponse) => {
    setEditingFollowUp(fu);
    followUpForm.setFieldsValue({
      follow_up_type: fu.follow_up_type,
      content: fu.content,
      next_step: fu.next_step,
      next_follow_up_at: fu.next_follow_up_at ? dayjs(fu.next_follow_up_at) : undefined,
    });
    setFollowUpOpen(true);
  };

  if (isLoading || !customer) {
    return (
      <div style={{ padding: 24, textAlign: "center" }}>
        <Spin />
      </div>
    );
  }

  return (
    <div style={{ padding: 24 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => router.push("/dashboard/customer")}>
          返回
        </Button>
        <h2 style={{ margin: 0 }}>{customer.name}</h2>
        <Tag color={LEVEL_COLORS[customer.level]}>
          {LEVEL_LABELS[customer.level] || customer.level}
        </Tag>
        {customer.is_active ? <Tag color="green">活跃</Tag> : <Tag color="red">已删除</Tag>}
        <div style={{ flex: 1 }} />
        <Button
          type="primary"
          icon={<RobotOutlined />}
          onClick={handleAiSuggest}
        >
          AI 智能建议
        </Button>
      </div>

      {/* 3 列布局 */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 16 }}>
        {/* 左:基础 + 公司 + 属性 + 备注 + 自定义字段 */}
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Card title="基础信息" size="small">
            <Descriptions column={1} size="small">
              <Descriptions.Item label="手机">{customer.phone || "—"}</Descriptions.Item>
              <Descriptions.Item label="邮箱">{customer.email || "—"}</Descriptions.Item>
              <Descriptions.Item label="微信">{customer.wechat || "—"}</Descriptions.Item>
              <Descriptions.Item label="性别">{customer.gender || "—"}</Descriptions.Item>
              <Descriptions.Item label="生日">{customer.birthday || "—"}</Descriptions.Item>
              <Descriptions.Item label="地址">{customer.address || "—"}</Descriptions.Item>
            </Descriptions>
          </Card>

          <Card title="公司信息" size="small">
            <Descriptions column={1} size="small">
              <Descriptions.Item label="公司">{customer.company_name || "—"}</Descriptions.Item>
              <Descriptions.Item label="职位">{customer.company_position || "—"}</Descriptions.Item>
              <Descriptions.Item label="行业">{customer.industry || "—"}</Descriptions.Item>
              <Descriptions.Item label="规模">{customer.company_size || "—"}</Descriptions.Item>
              <Descriptions.Item label="官网">
                {customer.company_website ? (
                  <a href={customer.company_website} target="_blank" rel="noopener noreferrer">
                    {customer.company_website}
                  </a>
                ) : "—"}
              </Descriptions.Item>
            </Descriptions>
          </Card>

          <Card title="客户属性" size="small">
            <Descriptions column={1} size="small">
              <Descriptions.Item label="等级">
                <Tag color={LEVEL_COLORS[customer.level]}>
                  {LEVEL_LABELS[customer.level] || customer.level}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="来源">{customer.source || "—"}</Descriptions.Item>
              <Descriptions.Item label="标签">
                {customer.tags?.length
                  ? customer.tags.map((t) => <Tag key={t}>{t}</Tag>)
                  : "—"}
              </Descriptions.Item>
              <Descriptions.Item label="负责人">{customer.owner_user_name || `#${customer.owner_user_id}`}</Descriptions.Item>
            </Descriptions>
          </Card>

          {customer.custom_fields_schema_resolved?.length > 0 && (
            <Card title="自定义字段" size="small">
              <Descriptions column={1} size="small">
                {customer.custom_fields_schema_resolved.map((f) => (
                  <Descriptions.Item key={f.key} label={f.label}>
                    {f.value === null || f.value === undefined || f.value === ""
                      ? <span style={{ color: "#999" }}>—</span>
                      : Array.isArray(f.value)
                        ? f.value.join(", ")
                        : String(f.value)}
                  </Descriptions.Item>
                ))}
              </Descriptions>
            </Card>
          )}

          <Card title="备注" size="small">
            <div style={{ whiteSpace: "pre-wrap" }}>{customer.remark || <span style={{ color: "#999" }}>无</span>}</div>
          </Card>

          <Card title="系统信息" size="small">
            <Descriptions column={1} size="small">
              <Descriptions.Item label="创建时间">
                {dayjs(customer.created_at).format("YYYY-MM-DD HH:mm")}
              </Descriptions.Item>
              <Descriptions.Item label="最近更新">
                {dayjs(customer.updated_at).format("YYYY-MM-DD HH:mm")}
              </Descriptions.Item>
              <Descriptions.Item label="跟进总数">{customer.follow_ups_count}</Descriptions.Item>
            </Descriptions>
          </Card>
        </Space>

        {/* 右:跟进 timeline */}
        <Card
          title="跟进时间线"
          size="small"
          extra={
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreateFollowUp}>
              新增跟进
            </Button>
          }
        >
          {(followUps?.items ?? []).length === 0 ? (
            <Empty description="暂无跟进记录" />
          ) : (
            <Timeline
              items={(followUps?.items ?? []).map((fu) => ({
                color: fu.ai_suggested ? "gold" : "blue",
                dot: fu.ai_suggested ? <ThunderboltOutlined /> : undefined,
                children: <FollowUpItem
                  fu={fu}
                  onEdit={() => openEditFollowUp(fu)}
                  onDelete={() => handleDeleteFollowUp(fu.id)}
                />,
              }))}
            />
          )}
        </Card>
      </div>

      {/* 跟进 Create/Edit Modal */}
      <Modal
        title={editingFollowUp ? "编辑跟进" : "新增跟进"}
        open={followUpOpen}
        onCancel={() => {
          setFollowUpOpen(false);
          setEditingFollowUp(null);
          followUpForm.resetFields();
        }}
        onOk={editingFollowUp ? handleUpdateFollowUp : handleCreateFollowUp}
        okText="保存"
        cancelText="取消"
        destroyOnClose
        width={640}
      >
        <Form form={followUpForm} layout="vertical">
          <Form.Item
            label="跟进类型"
            name="follow_up_type"
            rules={[{ required: true }]}
          >
            <Select
              options={Object.entries(FOLLOW_UP_TYPE_LABELS).map(([value, label]) => ({
                value,
                label,
              }))}
            />
          </Form.Item>
          <Form.Item label="跟进内容" name="content" rules={[{ required: true, min: 1, max: 5000 }]}>
            <Input.TextArea rows={4} placeholder="沟通了什么 / 客户反馈 / 下一步计划" />
          </Form.Item>
          <Form.Item label="下一步行动" name="next_step">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item label="下次跟进时间" name="next_follow_up_at">
            <DatePicker
              showTime
              style={{ width: "100%" }}
              placeholder="可选"
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* AI 智能建议 Drawer */}
      <Drawer
        title="AI 智能建议"
        open={aiOpen}
        onClose={() => {
          setAiOpen(false);
          setAiResult(null);
          setAiFocus("");
        }}
        width={560}
        footer={
          aiResult && (
            <Space>
              <Button onClick={() => setAiOpen(false)}>关闭</Button>
              <Button type="primary" onClick={handleAdoptAiSuggestion}>
                采纳并创建跟进
              </Button>
            </Space>
          )
        }
      >
        <div style={{ marginBottom: 12 }}>
          <Input.TextArea
            rows={2}
            placeholder="本次关注点(可选,例: 决策人沟通 / 价格谈判)"
            value={aiFocus}
            onChange={(e) => setAiFocus(e.target.value)}
            disabled={aiLoading}
          />
          <Button
            type="primary"
            loading={aiLoading}
            onClick={handleAiSuggest}
            style={{ marginTop: 8 }}
            disabled={!aiFocus}
          >
            重新生成
          </Button>
        </div>
        {aiLoading ? (
          <Spin />
        ) : aiResult ? (
          <Collapse
            defaultActiveKey={["message", "next", "reasoning"]}
            items={[
              {
                key: "message",
                label: "推荐话术",
                children: <div style={{ whiteSpace: "pre-wrap" }}>{aiResult.suggested_message}</div>,
              },
              {
                key: "next",
                label: "推荐跟进时间",
                children: aiResult.suggested_next_follow_up_at
                  ? dayjs(aiResult.suggested_next_follow_up_at).format("YYYY-MM-DD HH:mm")
                  : "—",
              },
              {
                key: "reasoning",
                label: "推理依据",
                children: (
                  <div style={{ whiteSpace: "pre-wrap", color: "#666" }}>
                    {aiResult.reasoning}
                  </div>
                ),
              },
              {
                key: "meta",
                label: "调用元数据",
                children: (
                  <div style={{ fontSize: 12, color: "#999" }}>
                    llm_call_id: {aiResult.llm_call_id}
                    <br />
                    duration_ms: {aiResult.duration_ms}
                  </div>
                ),
              },
            ]}
          />
        ) : null}
      </Drawer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 跟进 Timeline item
// ---------------------------------------------------------------------------

function FollowUpItem({
  fu,
  onEdit,
  onDelete,
}: {
  fu: FollowUpResponse;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const type = fu.follow_up_type as FollowUpType;
  return (
    <div>
      <Space size="small" style={{ marginBottom: 4 }}>
        <Tag color={FOLLOW_UP_TYPE_COLORS[type] || "default"}>
          {FOLLOW_UP_TYPE_LABELS[type] || fu.follow_up_type}
        </Tag>
        <span style={{ color: "#999", fontSize: 12 }}>
          {dayjs(fu.created_at).format("YYYY-MM-DD HH:mm")} · {fu.user_name || `#${fu.user_id}`}
        </span>
        {fu.ai_suggested && <Tag color="gold">AI 建议</Tag>}
      </Space>
      <div style={{ whiteSpace: "pre-wrap", marginTop: 4 }}>{fu.content}</div>
      {fu.next_step && (
        <div style={{ marginTop: 6, color: "#666", fontSize: 12 }}>
          下一步:<b>{fu.next_step}</b>
        </div>
      )}
      {fu.next_follow_up_at && (
        <div style={{ marginTop: 2, color: "#666", fontSize: 12 }}>
          原定下次:{dayjs(fu.next_follow_up_at).format("YYYY-MM-DD HH:mm")}
        </div>
      )}
      <Space size="small" style={{ marginTop: 8 }}>
        <Button size="small" onClick={onEdit}>
          编辑
        </Button>
        <Popconfirm
          title="确认删除这条跟进?"
          onConfirm={onDelete}
          okText="删除"
          cancelText="取消"
          okButtonProps={{ danger: true }}
        >
          <Button size="small" danger>
            删除
          </Button>
        </Popconfirm>
      </Space>
    </div>
  );
}