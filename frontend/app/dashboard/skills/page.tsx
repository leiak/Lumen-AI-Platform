"use client";

import { useState, useEffect } from "react";
import { Table, Button, Space, Modal, Form, Input, Select, Tag, message, Popconfirm, Card, Row, Col } from "antd";
import { PlusOutlined, DeleteOutlined, EditOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import api from "@/services/auth";

interface Skill {
  id: number;
  name: string;
  description?: string;
  category?: string;
  content: string;
  is_builtin: boolean;
  is_active: boolean;
  version: string;
}

const categories = [
  { value: "web", label: "Web" },
  { value: "data", label: "Data" },
  { value: "code", label: "Code" },
  { value: "chat", label: "Chat" },
  { value: "other", label: "Other" },
];

export default function SkillsPage() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [form] = Form.useForm();

  const fetchSkills = async () => {
    setLoading(true);
    try {
      const response = await api.get("/skills/");
      if (response.data.code === 200) {
        setSkills(response.data.data);
      }
    } catch (error) {
      message.error("获取技能列表失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSkills();
  }, []);

  const handleCreate = async (values: any) => {
    try {
      const response = await api.post("/skills/", values);
      if (response.data.code === 200) {
        message.success("创建成功");
        setModalVisible(false);
        form.resetFields();
        fetchSkills();
      }
    } catch (error) {
      message.error("创建失败");
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await api.delete(`/skills/${id}`);
      message.success("删除成功");
      fetchSkills();
    } catch (error) {
      message.error("删除失败");
    }
  };

  const columns: ColumnsType<Skill> = [
    { title: "ID", dataIndex: "id", key: "id", width: 60 },
    { title: "名称", dataIndex: "name", key: "name" },
    { title: "分类", dataIndex: "category", key: "category", render: (cat) => <Tag>{cat || "other"}</Tag> },
    { title: "描述", dataIndex: "description", key: "description", ellipsis: true },
    { title: "版本", dataIndex: "version", key: "version", width: 80 },
    { title: "内置", dataIndex: "is_builtin", key: "is_builtin", render: (builtin) => builtin ? <Tag color="blue">是</Tag> : <Tag>否</Tag> },
    {
      title: "操作",
      key: "action",
      render: (_, record) => (
        record.is_builtin ? <span>-</span> : (
          <Popconfirm title="确认删除?" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        )
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalVisible(true)}>
          添加技能
        </Button>
      </div>
      <Table columns={columns} dataSource={skills} rowKey="id" loading={loading} />

      <Modal title="添加技能" open={modalVisible} onCancel={() => setModalVisible(false)} footer={null} width={600}>
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Form.Item name="name" label="技能名称" rules={[{ required: true }]}>
            <Input placeholder="技能名称" />
          </Form.Item>
          <Form.Item name="category" label="分类">
            <Select options={categories} placeholder="选择分类" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="技能描述" />
          </Form.Item>
          <Form.Item name="content" label="技能内容" rules={[{ required: true }]}>
            <Input.TextArea placeholder="技能提示词或代码" rows={6} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit">创建</Button>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
