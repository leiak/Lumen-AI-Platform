"use client";
import { useState, useEffect } from "react";
import { Table, Button, Tag, Space, Select, App } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { skillAdminApi, MarketplaceSkill } from "@/services/skills";
import { SkillUpsertForm } from "@/components/skills/admin/SkillUpsertForm";
import { SkillTypeTag } from "@/components/skills/SkillTypeTag";

export default function AdminSkillsPage() {
  const { message } = App.useApp();
  const [skills, setSkills] = useState<MarketplaceSkill[]>([]);
  const [typeFilter, setTypeFilter] = useState<string | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<MarketplaceSkill | null>(null);
  const [showForm, setShowForm] = useState(false);

  const fetchSkills = async () => {
    setLoading(true);
    try {
      const res = await skillAdminApi.list(typeFilter);
      if (res.data.code === 200) {
        setSkills(res.data.data || []);
      }
    } catch (e) {
      message.error("加载技能列表失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSkills();
  }, [typeFilter]);

  const handleDelete = async (id: number) => {
    try {
      const r = await fetch(`/api/v1/admin/skills/${id}`, { method: "DELETE" });
      if (r.status === 409) {
        const j = await r.json();
        message.warning(j.detail || "技能正在被使用,无法删除");
        return;
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      message.success("删除成功");
      fetchSkills();
    } catch (e) {
      message.error(`删除失败: ${(e as Error).message}`);
    }
  };

  const columns = [
    { title: "名称", dataIndex: "name", key: "name" },
    {
      title: "类型", dataIndex: "type", key: "type",
      render: (t: string | undefined) => <SkillTypeTag type={t} />,
    },
    { title: "分类", dataIndex: "category", key: "category" },
    { title: "版本", dataIndex: "version", key: "version" },
    {
      title: "已认证", dataIndex: "is_verified", key: "is_verified",
      render: (v: boolean | undefined) =>
        v ? <Tag color="green">✓</Tag> : <Tag>—</Tag>,
    },
    { title: "下载", dataIndex: "downloads", key: "downloads" },
    {
      title: "操作", key: "action",
      render: (_: any, record: MarketplaceSkill) => (
        <Space>
          <Button
            size="small"
            onClick={() => { setEditing(record); setShowForm(true); }}
          >
            编辑
          </Button>
          <Button size="small" danger onClick={() => handleDelete(record.id)}>
            删除
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16, width: "100%", justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>技能管理</h2>
        <Space>
          <Select
            placeholder="筛选类型"
            allowClear
            value={typeFilter}
            onChange={setTypeFilter}
            style={{ width: 160 }}
            options={[
              { value: "prompt", label: "提示词" },
              { value: "script", label: "脚本" },
              { value: "http", label: "API" },
              { value: "knowledge_retrieval", label: "知识库" },
              { value: "tool", label: "工具" },
            ]}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => { setEditing(null); setShowForm(true); }}
          >
            新建技能
          </Button>
        </Space>
      </Space>
      <Table
        columns={columns}
        dataSource={skills}
        rowKey="id"
        loading={loading}
      />
      {showForm && (
        <SkillUpsertForm
          skill={editing}
          onSave={() => { setShowForm(false); fetchSkills(); }}
          onCancel={() => setShowForm(false)}
        />
      )}
    </div>
  );
}
