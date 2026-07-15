"use client";

import { useState, useEffect } from "react";
import {
  App,
  Table,
  Button,
  Space,
  Modal,
  Form,
  Input,
  Popconfirm,
  Tag,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { usersApi, User } from "@/services/users";

export default function UsersPage() {
  // antd v5: 必须用 App.useApp() 拿 message 才能 consume context
  // (静态 import { message } 在 strict mode 下不渲染 toast)
  const { message } = App.useApp();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [form] = Form.useForm();
  // Server-side pagination state. The /users/ endpoint returns a
  // PaginatedResponse; the previous Table had no pagination prop at all,
  // so the user saw the first server page (default page_size=10) with no
  // way to navigate.
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [total, setTotal] = useState(0);

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const response = await usersApi.list(page, pageSize);
      if (response.data.code === 200) {
        setUsers(response.data.data || []);
        setTotal(response.data.total || 0);
      }
    } catch (error) {
      message.error("获取用户列表失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize]);

  const handleCreate = async (values: {
    username: string;
    email: string;
    password: string;
    full_name?: string;
  }) => {
    try {
      const response = await usersApi.create(values);
      if (response.data.code === 200) {
        message.success("创建成功");
        setModalVisible(false);
        form.resetFields();
        fetchUsers();
      }
    } catch (error) {
      message.error("创建失败");
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await usersApi.delete(id);
      message.success("删除成功");
      fetchUsers();
    } catch (error) {
      message.error("删除失败");
    }
  };

  const columns: ColumnsType<User> = [
    {
      title: "ID",
      dataIndex: "id",
      key: "id",
      width: 80,
    },
    {
      title: "用户名",
      dataIndex: "username",
      key: "username",
    },
    {
      title: "邮箱",
      dataIndex: "email",
      key: "email",
    },
    {
      title: "姓名",
      dataIndex: "full_name",
      key: "full_name",
    },
    {
      title: "状态",
      dataIndex: "is_active",
      key: "is_active",
      render: (active) => (
        <Tag color={active ? "green" : "red"}>{active ? "启用" : "禁用"}</Tag>
      ),
    },
    {
      title: "角色",
      dataIndex: "is_superuser",
      key: "is_superuser",
      render: (superuser) => (
        <Tag color={superuser ? "blue" : "default"}>
          {superuser ? "管理员" : "普通用户"}
        </Tag>
      ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
    },
    {
      title: "操作",
      key: "action",
      render: (_, record) => (
        <Popconfirm
          title="确认删除?"
          onConfirm={() => handleDelete(record.id)}
        >
          <Button size="small" danger>
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 16 }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setModalVisible(true)}
        >
          创建用户
        </Button>
      </div>
      <Table
        columns={columns}
        dataSource={users}
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

      <Modal
        title="创建用户"
        open={modalVisible}
        onCancel={() => {
          setModalVisible(false);
          form.resetFields();
        }}
        footer={null}
      >
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, message: "请输入用户名" }]}
          >
            <Input placeholder="请输入用户名" />
          </Form.Item>
          <Form.Item
            name="email"
            label="邮箱"
            rules={[
              { required: true, message: "请输入邮箱" },
              { type: "email", message: "请输入有效邮箱" },
            ]}
          >
            <Input placeholder="请输入邮箱" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: "请输入密码" }]}
          >
            <Input.Password placeholder="请输入密码" />
          </Form.Item>
          <Form.Item name="full_name" label="姓名">
            <Input placeholder="请输入姓名" />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                创建
              </Button>
              <Button onClick={() => setModalVisible(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
