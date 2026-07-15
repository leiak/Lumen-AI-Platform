// frontend/app/dashboard/wx-publisher/drafts/page.tsx
// M32 — 公众号助手 — 草稿列表页.
//
// Spec §5.2 — Toolbar (新建 + 状态过滤 + 模板过滤 + 账号过滤 + 搜索)
// + DraftList 服务端分页.
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Button,
  Input,
  Select,
  Space,
  Modal,
  Form,
  message,
  Popconfirm,
} from "antd";
import { PlusOutlined, SearchOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { App } from "antd";
import { draftApi, type WxListParams } from "@/services/wx-publisher";
import { DraftList } from "@/components/wx-publisher/DraftList";
import type { WxDraftCreate } from "@/types/wx-publisher";

const PAGE_SIZE = 10;

export default function DraftsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const { message: toast } = App.useApp();
  const [params, setParams] = useState<WxListParams>({
    page: 1,
    page_size: PAGE_SIZE,
  });
  const [searchInput, setSearchInput] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm();

  const { data, isLoading } = useQuery({
    queryKey: ["wx-publisher", "drafts", params],
    queryFn: () => draftApi.list(params),
  });

  const handlePageChange = (page: number, pageSize: number) => {
    setParams((p) => ({ ...p, page, page_size: pageSize }));
  };

  const handleSearch = () => {
    setParams((p) => ({ ...p, page: 1, search: searchInput || undefined }));
  };

  const handleCreate = async () => {
    const values = await form.validateFields();
    try {
      const created = await draftApi.create({
        title: values.title,
        content_markdown: values.content_markdown ?? "",
      } satisfies WxDraftCreate);
      toast.success("草稿已创建");
      setCreateOpen(false);
      form.resetFields();
      qc.invalidateQueries({ queryKey: ["wx-publisher", "drafts"] });
      router.push(`/dashboard/wx-publisher/drafts/${created.id}`);
    } catch (err: any) {
      toast.error(err?.message || "创建失败");
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await draftApi.delete(id);
      toast.success("已删除");
      qc.invalidateQueries({ queryKey: ["wx-publisher", "drafts"] });
    } catch (err: any) {
      toast.error(err?.message || "删除失败");
    }
  };

  const handleDuplicate = async (id: number) => {
    try {
      const orig = await draftApi.get(id);
      const created = await draftApi.create({
        title: `${orig.title} (副本)`,
        content_markdown: orig.content_markdown,
      });
      toast.success("已复制");
      qc.invalidateQueries({ queryKey: ["wx-publisher", "drafts"] });
      router.push(`/dashboard/wx-publisher/drafts/${created.id}`);
    } catch (err: any) {
      toast.error(err?.message || "复制失败");
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginTop: 0 }}>草稿管理</h2>

      <Space
        wrap
        style={{ marginBottom: 16, width: "100%" }}
        size={8}
      >
        <Input
          placeholder="搜索标题"
          allowClear
          prefix={<SearchOutlined />}
          style={{ width: 220 }}
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onPressEnter={handleSearch}
        />
        <Select
          placeholder="状态"
          allowClear
          style={{ width: 140 }}
          onChange={(v) => setParams((p) => ({ ...p, page: 1, status: v }))}
          options={[
            { value: "draft", label: "草稿" },
            { value: "rendering", label: "排版中" },
            { value: "ready", label: "待发布" },
            { value: "publishing", label: "发布中" },
            { value: "published", label: "已发布" },
            { value: "failed", label: "失败" },
          ]}
        />
        <Button onClick={handleSearch}>搜索</Button>
        <div style={{ flex: 1 }} />
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setCreateOpen(true)}
        >
          新建草稿
        </Button>
      </Space>

      <DraftList
        items={data?.items ?? []}
        loading={isLoading}
        total={data?.total ?? 0}
        page={data?.page ?? 1}
        pageSize={data?.page_size ?? PAGE_SIZE}
        onPageChange={handlePageChange}
        onEdit={(id) => router.push(`/dashboard/wx-publisher/drafts/${id}`)}
        onDuplicate={handleDuplicate}
        onDelete={handleDelete}
      />

      <Modal
        title="新建草稿"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreate}
        okText="创建"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" initialValues={{ content_markdown: "" }}>
          <Form.Item
            name="title"
            label="标题"
            rules={[{ required: true, message: "请输入标题" }]}
          >
            <Input placeholder="例: AI Agent 在企业知识管理中的应用" />
          </Form.Item>
          <Form.Item name="content_markdown" label="Markdown 内容 (可选)">
            <Input.TextArea rows={4} placeholder="# 一、..." />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}