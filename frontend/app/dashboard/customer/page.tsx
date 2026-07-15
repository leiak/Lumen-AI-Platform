// frontend/app/dashboard/customer/page.tsx
// M33 — 客户管理(CRM) — 客户列表页.
//
// Spec §5.2 — Toolbar (新建 + 多维过滤 + 搜索) + 服务端分页 Table.
// 列表行: 姓名(链接到详情) | 手机(脱敏) | 公司 | 职位 | 等级 Tag | 来源 Tag |
//         标签 | 负责人 | 上次跟进 | 下次跟进(过期红色) | 操作(编辑/转单/删除).
"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Button,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Modal,
  Form,
  DatePicker,
  App,
  Popconfirm,
  Drawer,
  Divider,
} from "antd";
import {
  PlusOutlined,
  SearchOutlined,
  CalendarOutlined,
  BellOutlined,
} from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import dayjs, { type Dayjs } from "dayjs";
import { customerApi } from "@/services/customer";
import { authApi } from "@/services/auth";
import OwnerUserSelect from "@/components/customer/OwnerUserSelect";
import type {
  CustomerCreate,
  CustomerDetail,
  CustomerLevel,
  CustomerListItem,
  CustomerListParams,
  CustomerSource,
  CustomerUpdate,
  FollowUpResponse,
  FollowUpType,
  UpcomingFollowUpItem,
} from "@/types/customer";

const PAGE_SIZE = 20;

const LEVEL_OPTIONS: { value: CustomerLevel; label: string; color: string }[] = [
  { value: "vip", label: "VIP", color: "gold" },
  { value: "normal", label: "普通", color: "blue" },
  { value: "potential", label: "潜在", color: "cyan" },
  { value: "lost", label: "已流失", color: "default" },
];

const SOURCE_OPTIONS: { value: CustomerSource; label: string }[] = [
  { value: "referral", label: "推荐" },
  { value: "website", label: "官网" },
  { value: "exhibition", label: "展会" },
  { value: "ad", label: "广告" },
  { value: "other", label: "其他" },
];

const SORT_OPTIONS = [
  { value: "created_at_desc", label: "创建时间↓" },
  { value: "last_follow_up_at_desc", label: "最近跟进↓" },
  { value: "next_follow_up_at_asc", label: "下次跟进↑" },
  { value: "level_asc", label: "等级↑" },
];

export default function CustomerListPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const { message: toast, modal } = App.useApp();
  const [params, setParams] = useState<CustomerListParams>({
    page: 1,
    page_size: PAGE_SIZE,
    is_active: true,
  });
  const [searchInput, setSearchInput] = useState("");
  const [upcomingOpen, setUpcomingOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<CustomerDetail | null>(null);
  const [form] = Form.useForm();
  const [editForm] = Form.useForm();

  const { data, isLoading } = useQuery({
    queryKey: ["customer", "list", params],
    queryFn: () => customerApi.list(params),
  });

  /** 拉当前用户,用于「负责人」下拉默认值(规格 §5.2:负责人 Select,默认当前用户)。 */
  const { data: currentUser } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: async () => {
      const res = await authApi.getMe();
      return res.data.data;
    },
    staleTime: 5 * 60_000, // 1 个 session 内用户信息不变
  });

  /** 新建 Modal 打开 + 当前用户已加载 → 把 owner_user_id 推到默认值
   * (仅在字段还是空的时候推,避免覆盖用户已选过的值)。 */
  useEffect(() => {
    if (createOpen && currentUser?.id) {
      const current = form.getFieldValue("owner_user_id");
      if (current == null) {
        form.setFieldsValue({ owner_user_id: currentUser.id });
      }
    }
  }, [createOpen, currentUser?.id, form]);

  const handleSearch = () => {
    setParams((p) => ({ ...p, page: 1, keyword: searchInput || undefined }));
  };

  const handleLevelFilter = (levels: CustomerLevel[]) => {
    setParams((p) => ({ ...p, page: 1, levels: levels.length ? levels : undefined }));
  };

  const handleSourceFilter = (sources: CustomerSource[]) => {
    setParams((p) => ({ ...p, page: 1, sources: sources.length ? sources : undefined }));
  };

  const handleSortChange = (sort: string) => {
    setParams((p) => ({ ...p, page: 1, sort: sort || undefined }));
  };

  const handlePageChange = (page: number, pageSize: number) => {
    setParams((p) => ({ ...p, page, page_size: pageSize }));
  };

  const handleDelete = async (id: number, name: string) => {
    modal.confirm({
      title: `确认删除客户「${name}」?`,
      content: "软删操作,可在「已删除」中恢复。跟进记录保留。",
      okText: "删除",
      okType: "danger",
      cancelText: "取消",
      onOk: async () => {
        try {
          await customerApi.delete(id);
          toast.success("已删除");
          qc.invalidateQueries({ queryKey: ["customer"] });
        } catch (err: any) {
          toast.error(err?.message || "删除失败");
        }
      },
    });
  };

  const handleCreate = async () => {
    const values = await form.validateFields();
    try {
      const payload: CustomerCreate = {
        name: values.name,
        owner_user_id: values.owner_user_id,
        phone: values.phone,
        email: values.email,
        wechat: values.wechat,
        gender: values.gender,
        birthday: values.birthday ? values.birthday.format("YYYY-MM-DD") : undefined,
        address: values.address,
        company_name: values.company_name,
        company_position: values.company_position,
        industry: values.industry,
        company_size: values.company_size,
        company_website: values.company_website,
        level: values.level || "potential",
        source: values.source,
        tags: values.tags,
        remark: values.remark,
      };
      const created = await customerApi.create(payload);
      toast.success("客户已创建");
      setCreateOpen(false);
      form.resetFields();
      qc.invalidateQueries({ queryKey: ["customer", "list"] });
      router.push(`/dashboard/customer/${created.id}`);
    } catch (err: any) {
      if (err?.errorFields) return; // 表单校验失败,AntD 自己处理
      toast.error(err?.message || "创建失败");
    }
  };

  const handleEdit = (row: CustomerListItem) => {
    setEditing(row as unknown as CustomerDetail);
    editForm.setFieldsValue({
      name: row.name,
      owner_user_id: row.owner_user_id,
      level: row.level,
      source: row.source,
      tags: row.tags,
    });
  };

  const handleUpdate = async () => {
    if (!editing) return;
    const values = await editForm.validateFields();
    try {
      const payload: CustomerUpdate = {
        name: values.name,
        owner_user_id: values.owner_user_id,
        level: values.level,
        source: values.source,
        tags: values.tags,
      };
      await customerApi.update(editing.id, payload);
      toast.success("已更新");
      setEditing(null);
      qc.invalidateQueries({ queryKey: ["customer"] });
    } catch (err: any) {
      if (err?.errorFields) return;
      toast.error(err?.message || "更新失败");
    }
  };

  const columns = useMemo(
    () => [
      {
        title: "姓名",
        dataIndex: "name",
        key: "name",
        render: (text: string, row: CustomerListItem) => (
          <a onClick={() => router.push(`/dashboard/customer/${row.id}`)}>
            {text}
          </a>
        ),
      },
      {
        title: "手机",
        dataIndex: "phone_masked",
        key: "phone_masked",
        width: 130,
        render: (text?: string | null) => text || "—",
      },
      {
        title: "公司 / 职位",
        key: "company",
        width: 200,
        render: (_: any, row: CustomerListItem) => (
          <span>
            {row.company_name || "—"}
            {row.company_position ? ` / ${row.company_position}` : ""}
          </span>
        ),
      },
      {
        title: "等级",
        dataIndex: "level",
        key: "level",
        width: 80,
        render: (level: string) => {
          const opt = LEVEL_OPTIONS.find((o) => o.value === level);
          return opt ? <Tag color={opt.color}>{opt.label}</Tag> : <Tag>{level}</Tag>;
        },
      },
      {
        title: "来源",
        dataIndex: "source",
        key: "source",
        width: 80,
        render: (s?: string | null) => {
          if (!s) return "—";
          const opt = SOURCE_OPTIONS.find((o) => o.value === s);
          return opt ? <Tag>{opt.label}</Tag> : <Tag>{s}</Tag>;
        },
      },
      {
        title: "标签",
        dataIndex: "tags",
        key: "tags",
        render: (tags?: string[] | null) =>
          tags?.length ? tags.map((t) => <Tag key={t}>{t}</Tag>) : "—",
      },
      {
        title: "负责人",
        key: "owner",
        width: 90,
        render: (_: any, row: CustomerListItem) => row.owner_user_name || `#${row.owner_user_id}`,
      },
      {
        title: "下次跟进",
        dataIndex: "next_follow_up_at",
        key: "next_follow_up_at",
        width: 140,
        render: (text?: string | null, row?: CustomerListItem) => {
          if (!text) return "—";
          const d = dayjs(text);
          const now = dayjs();
          const overdue = d.isBefore(now);
          return (
            <span style={{ color: overdue ? "#cf1322" : undefined }}>
              {d.format("YYYY-MM-DD")}
              {overdue ? " ⚠️" : ""}
            </span>
          );
        },
      },
      {
        title: "操作",
        key: "actions",
        width: 180,
        render: (_: any, row: CustomerListItem) => (
          <Space size="small">
            <Button size="small" onClick={() => router.push(`/dashboard/customer/${row.id}`)}>
              详情
            </Button>
            <Button size="small" onClick={() => handleEdit(row)}>
              编辑
            </Button>
            <Button size="small" danger onClick={() => handleDelete(row.id, row.name)}>
              删除
            </Button>
          </Space>
        ),
      },
    ],
    [router],
  );

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginTop: 0 }}>客户管理</h2>

      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          placeholder="搜索姓名 / 手机 / 邮箱 / 公司"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onPressEnter={handleSearch}
          style={{ width: 260 }}
          allowClear
          prefix={<SearchOutlined />}
        />
        <Select
          mode="multiple"
          placeholder="等级"
          style={{ width: 160 }}
          allowClear
          options={LEVEL_OPTIONS}
          onChange={handleLevelFilter}
        />
        <Select
          mode="multiple"
          placeholder="来源"
          style={{ width: 160 }}
          allowClear
          options={SOURCE_OPTIONS}
          onChange={handleSourceFilter}
        />
        <Select
          placeholder="排序"
          style={{ width: 160 }}
          allowClear
          options={SORT_OPTIONS}
          onChange={handleSortChange}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          新建客户
        </Button>
        <Button icon={<BellOutlined />} onClick={() => setUpcomingOpen(true)}>
          待跟进
        </Button>
        <Button onClick={() => router.push("/dashboard/customer/settings")}>
          字段管理
        </Button>
      </Space>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={data?.items ?? []}
        loading={isLoading}
        pagination={{
          current: data?.page ?? 1,
          pageSize: data?.page_size ?? PAGE_SIZE,
          total: data?.total ?? 0,
          showSizeChanger: true,
          onChange: handlePageChange,
        }}
      />

      {/* 新建 Modal */}
      <Modal
        title="新建客户"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreate}
        okText="创建"
        cancelText="取消"
        width={720}
        destroyOnClose
      >
        <Form form={form} layout="vertical" initialValues={{ level: "potential" }}>
          <h4>基础信息</h4>
          <Form.Item label="姓名" name="name" rules={[{ required: true, max: 100 }]}>
            <Input placeholder="客户姓名" />
          </Form.Item>
          <Form.Item
            label="负责人"
            name="owner_user_id"
            rules={[{ required: true, type: "number" }]}
            extra={
              currentUser
                ? `默认是当前用户(${currentUser.full_name || currentUser.username})`
                : undefined
            }
          >
            <OwnerUserSelect />
          </Form.Item>
          <Space style={{ width: "100%" }}>
            <Form.Item label="手机" name="phone" style={{ flex: 1 }}>
              <Input placeholder="可选" />
            </Form.Item>
            <Form.Item label="邮箱" name="email" style={{ flex: 1 }}>
              <Input placeholder="可选" />
            </Form.Item>
            <Form.Item label="微信" name="wechat" style={{ flex: 1 }}>
              <Input placeholder="可选" />
            </Form.Item>
          </Space>
          <Space style={{ width: "100%" }}>
            <Form.Item label="性别" name="gender" style={{ width: 120 }}>
              <Select
                placeholder="可选"
                allowClear
                options={[
                  { value: "M", label: "男" },
                  { value: "F", label: "女" },
                  { value: "U", label: "未知" },
                ]}
              />
            </Form.Item>
            <Form.Item label="生日" name="birthday" style={{ width: 200 }}>
              <DatePicker style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item label="地址" name="address" style={{ flex: 1 }}>
              <Input placeholder="可选" />
            </Form.Item>
          </Space>

          <Divider />
          <h4>公司信息</h4>
          <Space style={{ width: "100%" }}>
            <Form.Item label="公司名" name="company_name" style={{ flex: 1 }}>
              <Input placeholder="可选" />
            </Form.Item>
            <Form.Item label="职位" name="company_position" style={{ flex: 1 }}>
              <Input placeholder="可选" />
            </Form.Item>
          </Space>
          <Space style={{ width: "100%" }}>
            <Form.Item label="行业" name="industry" style={{ width: 160 }}>
              <Input placeholder="IT/金融/..." />
            </Form.Item>
            <Form.Item label="规模" name="company_size" style={{ width: 140 }}>
              <Select
                placeholder="可选"
                allowClear
                options={[
                  { value: "1-10", label: "1-10" },
                  { value: "11-50", label: "11-50" },
                  { value: "51-200", label: "51-200" },
                  { value: "201-1000", label: "201-1000" },
                  { value: "1000+", label: "1000+" },
                ]}
              />
            </Form.Item>
            <Form.Item label="官网" name="company_website" style={{ flex: 1 }}>
              <Input placeholder="https://..." />
            </Form.Item>
          </Space>

          <Divider />
          <h4>客户属性</h4>
          <Space style={{ width: "100%" }}>
            <Form.Item label="等级" name="level" style={{ width: 120 }}>
              <Select options={LEVEL_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
            </Form.Item>
            <Form.Item label="来源" name="source" style={{ width: 120 }}>
              <Select placeholder="可选" allowClear options={SOURCE_OPTIONS} />
            </Form.Item>
            <Form.Item label="标签" name="tags" style={{ flex: 1 }}>
              <Select mode="tags" placeholder="Enter 添加" />
            </Form.Item>
          </Space>
          <Form.Item label="备注" name="remark">
            <Input.TextArea rows={3} placeholder="可粘贴任意模块的引用" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑 Modal(简化版,只改基础字段) */}
      <Modal
        title="编辑客户"
        open={!!editing}
        onCancel={() => setEditing(null)}
        onOk={handleUpdate}
        okText="保存"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={editForm} layout="vertical">
          <Form.Item label="姓名" name="name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item
            label="负责人"
            name="owner_user_id"
            rules={[{ required: true, type: "number" }]}
            extra="转单:把客户转给同租户的其他 active 用户"
          >
            <OwnerUserSelect />
          </Form.Item>
          <Form.Item label="等级" name="level">
            <Select options={LEVEL_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
          </Form.Item>
          <Form.Item label="来源" name="source">
            <Select allowClear options={SOURCE_OPTIONS} />
          </Form.Item>
          <Form.Item label="标签" name="tags">
            <Select mode="tags" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 待跟进 Drawer */}
      <UpcomingFollowUpsDrawer
        open={upcomingOpen}
        onClose={() => setUpcomingOpen(false)}
        onCustomerClick={(id) => {
          setUpcomingOpen(false);
          router.push(`/dashboard/customer/${id}`);
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// 待跟进 Drawer(内联,避免 components/ 目录分散)
// ---------------------------------------------------------------------------

function UpcomingFollowUpsDrawer({
  open,
  onClose,
  onCustomerClick,
}: {
  open: boolean;
  onClose: () => void;
  onCustomerClick: (id: number) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["customer", "upcoming-follow-ups", 7],
    queryFn: () => customerApi.upcomingFollowUps({ days: 7 }),
    enabled: open,
  });

  const items = data?.items ?? [];

  return (
    <Drawer
      title="待跟进客户(7 天内)"
      open={open}
      onClose={onClose}
      width={520}
    >
      {isLoading ? (
        <div>加载中…</div>
      ) : items.length === 0 ? (
        <div style={{ color: "#999" }}>暂无待跟进客户</div>
      ) : (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          {items.map((it) => (
            <UpcomingFollowUpCard
              key={it.customer_id}
              item={it}
              onClick={() => onCustomerClick(it.customer_id)}
            />
          ))}
        </Space>
      )}
    </Drawer>
  );
}

function UpcomingFollowUpCard({
  item,
  onClick,
}: {
  item: UpcomingFollowUpItem;
  onClick: () => void;
}) {
  const overdue = item.days_until_due < 0;
  const soon = item.days_until_due >= 0 && item.days_until_due <= 2;
  return (
    <div
      style={{
        padding: 12,
        border: "1px solid #f0f0f0",
        borderRadius: 6,
        cursor: "pointer",
        background: overdue ? "#fff1f0" : soon ? "#fffbe6" : "white",
      }}
      onClick={onClick}
    >
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <strong>{item.customer_name}</strong>
        <Tag color={LEVEL_OPTIONS.find((l) => l.value === item.level)?.color}>
          {LEVEL_OPTIONS.find((l) => l.value === item.level)?.label || item.level}
        </Tag>
      </div>
      <div style={{ marginTop: 6, fontSize: 12, color: "#666" }}>
        <CalendarOutlined /> {dayjs(item.next_follow_up_at).format("YYYY-MM-DD HH:mm")}
        {" · "}
        <span style={{ color: overdue ? "#cf1322" : soon ? "#d48806" : "#666" }}>
          {overdue
            ? `已过期 ${-item.days_until_due} 天`
            : item.days_until_due === 0
              ? "今天"
              : `${item.days_until_due} 天后`}
        </span>
      </div>
      {item.last_follow_up_content && (
        <div style={{ marginTop: 4, fontSize: 12, color: "#999" }}>
          上次:{item.last_follow_up_content}
        </div>
      )}
    </div>
  );
}