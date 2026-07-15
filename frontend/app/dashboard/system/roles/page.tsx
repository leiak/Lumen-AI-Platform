"use client";

import { useState, useEffect } from "react";
import { Table, Button, Space, Modal, Form, Input, Select, message, Popconfirm } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import api from "@/services/auth";

interface Permission {
  id: number;
  name: string;
  resource?: string;
  action?: string;
}

interface Role {
  id: number;
  name: string;
  description?: string;
  is_active: boolean;
  permissions: Permission[];
}

export default function RolesPage() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [form] = Form.useForm();

  const fetchRoles = async () => {
    setLoading(true);
    try {
      const response = await api.get("/roles/");
      if (response.data.code === 200) {
        setRoles(response.data.data);
      }
    } catch (error) {
      message.error("获取角色列表失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRoles();
  }, []);

  const handleCreate = async (values: { name: string; description?: string }) => {
    try {
      const response = await api.post("/roles/", values);
      if (response.data.code === 200) {
        message.success("创建成功");
        setModalVisible(false);
        form.resetFields();
        fetchRoles();
      }
    } catch (error) {
      message.error("创建失败");
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await api.delete(`/roles/${id}`);
      message.success("删除成功");
      fetchRoles();
    } catch (error) {
      message.error("删除失败");
    }
  };

  const columns: ColumnsType<Role> = [
    { title: "ID", dataIndex: "id", key: "id", width: 80 },
    { title: "名称", dataIndex: "name", key: "name" },
    { title: "描述", dataIndex: "description", key: "description" },
    { title: "状态", dataIndex: "is_active", key: "is_active", render: (active) => active ? "启用" : "禁用" },
    {
      title: "操作",
      key: "action",
      render: (_, record) => (
        <Popconfirm title="确认删除?" onConfirm={() => handleDelete(record.id)}>
          <Button size="small" danger>删除</Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalVisible(true)}>
          创建角色
        </Button>
      </div>
      <Table columns={columns} dataSource={roles} rowKey="id" loading={loading} />

      <Modal title="创建角色" open={modalVisible} onCancel={() => setModalVisible(false)} footer={null}>
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Form.Item name="name" label="角色名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit">创建</Button>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
