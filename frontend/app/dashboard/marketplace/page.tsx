"use client";

import { useEffect, useState } from "react";
import {
  Card,
  Col,
  Row,
  Input,
  Select,
  Tag,
  Button,
  Space,
  message,
  Spin,
  Empty,
  Pagination,
} from "antd";
import {
  SearchOutlined,
  DownloadOutlined,
  UserOutlined,
  AppstoreOutlined,
} from "@ant-design/icons";
import { useRouter } from "next/navigation";
import {
  workflowTemplateApi,
  WorkflowTemplate,
} from "@/services/workflowTemplate";

const { Search } = Input;

export default function MarketplacePage() {
  const router = useRouter();
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(12);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string | undefined>(undefined);
  const [categories, setCategories] = useState<{ value: string; count: number }[]>([]);
  const [importingId, setImportingId] = useState<number | null>(null);

  const fetchTemplates = async () => {
    setLoading(true);
    try {
      const res = await workflowTemplateApi.list({
        page,
        page_size: pageSize,
        search: search || undefined,
        category: category || undefined,
      });
      if (res.data.code === 200) {
        setTemplates(res.data.data || []);
        // Surface the real server total so the Pagination control can
        // render an accurate page count.
        setTotal(res.data.total || (res.data.data || []).length);
      }
    } catch (err) {
      message.error("加载模板失败");
    } finally {
      setLoading(false);
    }
  };

  const fetchCategories = async () => {
    try {
      const res = await workflowTemplateApi.categories();
      if (res.data.code === 200) {
        setCategories(res.data.data || []);
      }
    } catch (err) {
      // Non-fatal: categories dropdown is non-critical.
      message.error("加载技能分类失败");
    }
  };

  useEffect(() => {
    fetchTemplates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category, page, pageSize, search]);

  useEffect(() => {
    fetchCategories();
  }, []);

  const handleSearch = (value: string) => {
    setSearch(value);
    // Reset to first page whenever the query changes so users see fresh
    // results, not whatever page they were on.
    setPage(1);
  };

  const handleImport = async (tpl: WorkflowTemplate) => {
    setImportingId(tpl.id);
    try {
      const res = await workflowTemplateApi.import(tpl.id);
      if (res.data.code === 200) {
        message.success(`已基于模板 "${tpl.name}" 创建新工作流`);
        const newId = res.data.data?.workflow_id;
        if (newId) {
          router.push(`/dashboard/workflow/designer?id=${newId}`);
        } else {
          router.push(`/dashboard/workflow`);
        }
      }
    } catch (err) {
      message.error("导入失败");
    } finally {
      setImportingId(null);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={
          <Space>
            <AppstoreOutlined />
            <span>工作流模板市场</span>
          </Space>
        }
        extra={
          <Space>
            <Search
              placeholder="搜索模板名称"
              allowClear
              onSearch={handleSearch}
              style={{ width: 220 }}
            />
            <Select
              placeholder="选择分类"
              allowClear
              value={category}
              onChange={(v) => setCategory(v)}
              style={{ width: 180 }}
              options={categories.map((c) => ({ value: c.value, label: `${c.value} (${c.count})` }))}
            />
          </Space>
        }
      >
        {loading ? (
          <div style={{ textAlign: "center", padding: 48 }}>
            <Spin />
          </div>
        ) : templates.length === 0 ? (
          <Empty description="暂无可用模板" />
        ) : (
          <>
            <Row gutter={[16, 16]}>
              {templates.map((tpl) => (
                <Col key={tpl.id} xs={24} sm={12} md={8} lg={6}>
                  <Card
                    hoverable
                    size="small"
                    title={tpl.name}
                    extra={<Tag color="blue">{tpl.category}</Tag>}
                    style={{ height: "100%" }}
                  >
                    <div
                      style={{
                        color: "#666",
                        minHeight: 48,
                        marginBottom: 12,
                        fontSize: 13,
                      }}
                    >
                      {tpl.description || "无描述"}
                    </div>
                    <Space wrap style={{ marginBottom: 8 }}>
                      {tpl.tags?.map((tag) => (
                        <Tag key={tag}>{tag}</Tag>
                      ))}
                    </Space>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        fontSize: 12,
                        color: "#888",
                        marginBottom: 12,
                      }}
                    >
                      <span>
                        <UserOutlined /> {tpl.author_name || "anonymous"}
                      </span>
                      <span>
                        <DownloadOutlined /> {tpl.downloads}
                      </span>
                    </div>
                    <Button
                      type="primary"
                      block
                      icon={<DownloadOutlined />}
                      loading={importingId === tpl.id}
                      onClick={() => handleImport(tpl)}
                    >
                      使用此模板
                    </Button>
                  </Card>
                </Col>
              ))}
            </Row>
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 16 }}>
              <Pagination
                current={page}
                pageSize={pageSize}
                total={total}
                showSizeChanger
                showTotal={(t) => `共 ${t} 条`}
                onChange={(p, ps) => {
                  setPage(p);
                  setPageSize(ps);
                }}
              />
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
