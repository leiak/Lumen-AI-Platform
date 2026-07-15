"use client";

import { useState, useEffect } from "react";
import { Table, Button, Modal, Form, Input, message, Popconfirm, Card, Space } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { nlpApi, NLPQA } from "@/services/nlp";

export default function NLPQAPage() {
  const [data, setData] = useState<NLPQA[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();

  const fetchData = async () => {
    setLoading(true);
    try {
      // Pass page_size=100 so the server returns the full list (the
      // Table's local pager slices it client-side). The endpoint is
      // already paginated server-side — `total` from the response is
      // the real backend count.
      const response = await nlpApi.listQA(1, 100);
      if (response.data.code === 200) {
        setData(response.data.data || []);
        setTotal(response.data.total || (response.data.data || []).length);
      }
    } catch (error) {
      message.error("获取问答列表失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleCreate = async (values: any) => {
    setSubmitting(true);
    try {
      const response = await nlpApi.createQA(values);
      if (response.data.code === 200) {
        message.success("创建成功");
        setModalVisible(false);
        form.resetFields();
        fetchData();
      }
    } catch (error) {
      message.error("创建失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdate = async (values: any) => {
    if (!editingId) return;
    setSubmitting(true);
    try {
      const response = await nlpApi.updateQA(editingId, values);
      if (response.data.code === 200) {
        message.success("更新成功");
        setModalVisible(false);
        setEditingId(null);
        form.resetFields();
        fetchData();
      }
    } catch (error) {
      message.error("更新失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    setSubmitting(true);
    try {
      const response = await nlpApi.deleteQA(id);
      if (response.data.code === 200) {
        message.success("删除成功");
        fetchData();
      }
    } catch (error) {
      message.error("删除失败");
    } finally {
      setSubmitting(false);
    }
  };

  const columns = [
    { title: "ID", dataIndex: "id", key: "id" },
    { title: "问题", dataIndex: "question", key: "question", ellipsis: true },
    { title: "答案", dataIndex: "answer", key: "answer", ellipsis: true },
    { title: "创建时间", dataIndex: "created_at", key: "created_at" },
    {
      title: "操作",
      key: "action",
      render: (_: any, record: NLPQA) => (
        <Space>
          <Button size="small" onClick={() => { setEditingId(record.id); form.setFieldsValue(record); setModalVisible(true); }}>编辑</Button>
          <Popconfirm title="确认删除?" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger loading={submitting}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Card title="NLP 问答管理" extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingId(null); form.resetFields(); setModalVisible(true); }}>
          添加问答
        </Button>
      }>
        <Table
          columns={columns}
          dataSource={data}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 10, total, showTotal: (t) => `共 ${t} 条` }}
        />
      </Card>
      <Modal
        title={editingId ? "编辑问答" : "添加问答"}
        open={modalVisible}
        onCancel={() => { setModalVisible(false); setEditingId(null); form.resetFields(); }}
        footer={null}
      >
        <Form form={form} layout="vertical" onFinish={editingId ? handleUpdate : handleCreate}>
          <Form.Item name="question" label="问题" rules={[{ required: true, message: "请输入问题" }]}>
            <Input.TextArea placeholder="请输入问题" rows={3} />
          </Form.Item>
          <Form.Item name="answer" label="答案" rules={[{ required: true, message: "请输入答案" }]}>
            <Input.TextArea placeholder="请输入答案" rows={5} />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={submitting}>{editingId ? "更新" : "创建"}</Button>
              <Button onClick={() => { setModalVisible(false); setEditingId(null); }}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
