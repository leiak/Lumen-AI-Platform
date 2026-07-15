// frontend/app/dashboard/wx-publisher/templates/page.tsx
// M32 — 公众号助手 — 模板库页.
//
// Spec §5.4 — Toolbar (分类 Tab + 搜索) + Card 网格.
"use client";

import { useState } from "react";
import {
  Input,
  Tabs,
  Row,
  Col,
  Empty,
  Drawer,
  Tag,
  Button,
  Space,
  App,
} from "antd";
import { SearchOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { templateApi } from "@/services/wx-publisher";
import { TemplateCard } from "@/components/wx-publisher/TemplateCard";
import type { WxTemplateListItem, WxTemplateCategory } from "@/types/wx-publisher";

const PAGE_SIZE = 24;

const CATEGORIES: Array<{ key: WxTemplateCategory | "all"; label: string }> = [
  { key: "all", label: "全部" },
  { key: "minimal", label: "极简" },
  { key: "tech", label: "科技" },
  { key: "magazine", label: "杂志" },
  { key: "literary", label: "文艺" },
  { key: "business", label: "商务" },
];

export default function TemplatesPage() {
  const { message: toast } = App.useApp();
  const [category, setCategory] = useState<WxTemplateCategory | "all">("all");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [previewing, setPreviewing] = useState<WxTemplateListItem | null>(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["wx-publisher", "templates", category, search],
    queryFn: () =>
      templateApi.list({
        page: 1,
        page_size: PAGE_SIZE,
        category: category === "all" ? undefined : category,
        search: search || undefined,
      }),
  });
  // 缩略图生成后, refresh query 让 has_thumbnail / thumbnail_url 同步
  const handleThumbnailGenerated = (templateId: number) => {
    void refetch();
  };

  const handleApply = (template: WxTemplateListItem) => {
    toast.success(`已选择模板「${template.name}」, 在草稿编辑页应用.`);
  };

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginTop: 0 }}>排版模板</h2>

      <Tabs
        activeKey={category}
        onChange={(k) => setCategory(k as WxTemplateCategory | "all")}
        items={CATEGORIES.map((c) => ({ key: c.key, label: c.label }))}
        tabBarExtraContent={
          <Input
            placeholder="搜索模板"
            allowClear
            prefix={<SearchOutlined />}
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onPressEnter={() => setSearch(searchInput)}
            style={{ width: 220 }}
          />
        }
      />

      {data?.items.length === 0 ? (
        <Empty description="暂无模板" />
      ) : (
        <Row gutter={[16, 16]}>
          {(data?.items ?? []).map((tpl) => (
            <Col key={tpl.id} xs={24} sm={12} md={8} lg={6}>
              <TemplateCard
                template={tpl}
                onApply={handleApply}
                onPreview={(t) => setPreviewing(t)}
                onThumbnailGenerated={handleThumbnailGenerated}
              />
            </Col>
          ))}
        </Row>
      )}

      <Drawer
        title={previewing ? `预览: ${previewing.name}` : "预览"}
        open={!!previewing}
        onClose={() => setPreviewing(null)}
        width={720}
      >
        {previewing && (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Tag color="blue">{previewing.category}</Tag>
            {previewing.description && (
              <div style={{ color: "#666" }}>{previewing.description}</div>
            )}
            <Button type="primary" onClick={() => handleApply(previewing)}>
              应用此模板
            </Button>
            <div style={{ marginTop: 12 }}>
              <h4>使用次数: {previewing.usage_count}</h4>
            </div>
          </Space>
        )}
      </Drawer>
    </div>
  );
}