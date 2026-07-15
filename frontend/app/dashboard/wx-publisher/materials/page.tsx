// frontend/app/dashboard/wx-publisher/materials/page.tsx
// M32 — 公众号助手 — 素材库页.
//
// Spec §5.5 — Toolbar (+手动录入 +从 KB 选材 + 来源过滤) +
// MaterialList + 手动录入 Modal + KBImportModal.
"use client";

import { useState } from "react";
import {
  Button,
  Space,
  Modal,
  Form,
  Input,
  Select,
  Card,
  Tag,
  Empty,
  App,
} from "antd";
import { PlusOutlined, DatabaseOutlined, EditOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { materialApi, type WxListParams } from "@/services/wx-publisher";
import { knowledgeApi } from "@/services/knowledge";
import { MaterialList } from "@/components/wx-publisher/MaterialList";
import { KBImportModal } from "@/components/wx-publisher/KBImportModal";
import type { WxMaterialCreate } from "@/types/wx-publisher";
import type { KnowledgeBase } from "@/types/api";

const PAGE_SIZE = 20;

export default function MaterialsPage() {
  const qc = useQueryClient();
  const { message: toast } = App.useApp();
  const [params, setParams] = useState<WxListParams>({
    page: 1,
    page_size: PAGE_SIZE,
  });
  const [createOpen, setCreateOpen] = useState(false);
  const [kbImportOpen, setKbImportOpen] = useState(false);
  const [form] = Form.useForm();

  const { data, isLoading } = useQuery({
    queryKey: ["wx-publisher", "materials", params],
    queryFn: () => materialApi.list(params),
  });

  const { data: kbData } = useQuery({
    queryKey: ["knowledge", "list-for-materials"],
    queryFn: async () => {
      const res = await knowledgeApi.list(1, 100);
      // knowledgeApi.list 返 { data: PaginatedResponse<KnowledgeBase> }
      return (res.data?.data ?? []) as KnowledgeBase[];
    },
  });

  const handleCreate = async () => {
    const values = await form.validateFields();
    try {
      const tags = values.tags
        ? values.tags.split(",").map((t: string) => t.trim()).filter(Boolean)
        : [];
      await materialApi.create({
        title: values.title,
        content: values.content,
        tags,
      } satisfies WxMaterialCreate);
      toast.success("素材已添加");
      setCreateOpen(false);
      form.resetFields();
      qc.invalidateQueries({ queryKey: ["wx-publisher", "materials"] });
    } catch (err: any) {
      toast.error(err?.message || "添加失败");
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await materialApi.delete(id);
      toast.success("已删除");
      qc.invalidateQueries({ queryKey: ["wx-publisher", "materials"] });
    } catch (err: any) {
      toast.error(err?.message || "删除失败");
    }
  };

  const allTags = Array.from(
    new Set(
      (data?.items ?? []).flatMap((m) => m.tags ?? [])
    )
  );

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginTop: 0 }}>素材库</h2>

      <Space wrap style={{ marginBottom: 16, width: "100%" }} size={8}>
        <Button
          type="primary"
          icon={<EditOutlined />}
          onClick={() => setCreateOpen(true)}
        >
          手动录入
        </Button>
        <Button
          icon={<DatabaseOutlined />}
          onClick={() => setKbImportOpen(true)}
        >
          从 KB 选材
        </Button>
        <Select
          placeholder="来源"
          allowClear
          style={{ width: 120 }}
          onChange={(v) =>
            setParams((p) => ({ ...p, page: 1, source_type: v }))
          }
          options={[
            { value: "kb", label: "知识库" },
            { value: "manual", label: "手动" },
          ]}
        />
        {allTags.length > 0 && (
          <Select
            placeholder="按标签筛选"
            allowClear
            style={{ width: 160 }}
            onChange={(v) => setParams((p) => ({ ...p, page: 1, tag: v }))}
            options={allTags.map((t) => ({ value: t, label: t }))}
          />
        )}
      </Space>

      <Card styles={{ body: { padding: 0 } }}>
        {data?.items.length === 0 && !isLoading ? (
          <div style={{ padding: 32 }}>
            <Empty description="暂无素材, 点击「手动录入」或「从 KB 选材」开始" />
          </div>
        ) : (
          <MaterialList
            items={data?.items ?? []}
            loading={isLoading}
            onDelete={handleDelete}
          />
        )}
      </Card>

      <Modal
        title="手动录入素材"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreate}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="title"
            label="标题"
            rules={[{ required: true, message: "请输入标题" }]}
          >
            <Input placeholder="例: AI Agent 行业洞察 - 数据点" />
          </Form.Item>
          <Form.Item
            name="content"
            label="内容"
            rules={[{ required: true, message: "请输入内容" }]}
          >
            <Input.TextArea rows={6} placeholder="Markdown / 纯文本" />
          </Form.Item>
          <Form.Item name="tags" label="标签 (逗号分隔)">
            <Input placeholder="例: AI, 行业洞察" />
          </Form.Item>
        </Form>
      </Modal>

      <KBImportModal
        open={kbImportOpen}
        onClose={() => setKbImportOpen(false)}
        kbList={kbData ?? []}
        onImported={(count) => {
          toast.success(`已导入 ${count} 条素材`);
          qc.invalidateQueries({ queryKey: ["wx-publisher", "materials"] });
        }}
      />
    </div>
  );
}