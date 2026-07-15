"use client";

import { useCallback, useEffect, useState } from "react";
import { Input, Select, Space, Button, Row, Col, Modal, Empty, App as AntdApp } from "antd";
import { SearchOutlined, ReloadOutlined, ImportOutlined, ArrowLeftOutlined } from "@ant-design/icons";
import { useRouter } from "next/navigation";

import { workflowTemplateApi, WorkflowTemplate, WorkflowTemplateDetail, ImportResult } from "@/services/workflowTemplate";
import { useAppMessage, extractErrorDetail } from "../hooks/useAppMessage";
import { TemplateCard } from "../components/TemplateCard";
import { TemplatePreview } from "../components/TemplatePreview";

/**
 * M30b: workflow template marketplace.
 *
 * The page is a thin orchestrator: a search/filter bar + a 3-column
 * grid of TemplateCards + a preview drawer + an import-confirm
 * modal. All data fetching goes through `workflowTemplateApi`
 * (already wired in M22, but unused until now).
 */
export default function TemplatesPage() {
  const { message } = useAppMessage();
  void AntdApp; // ensure antd <App> context — useAppMessage reads from it
  const router = useRouter();

  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(12);

  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string | undefined>(undefined);
  const [tag, setTag] = useState<string | undefined>(undefined);
  const [categories, setCategories] = useState<{ value: string; count: number }[]>([]);

  const [previewId, setPreviewId] = useState<number | null>(null);
  const [importTarget, setImportTarget] = useState<WorkflowTemplate | null>(null);
  const [importing, setImporting] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await workflowTemplateApi.list({
        page,
        page_size: pageSize,
        search: search || undefined,
        category,
        tag,
      });
      const body: any = res.data;
      if (body.code === 200) {
        // /workflow-templates/ may return a paginated envelope OR
        // a flat list depending on backend version; handle both.
        const items = Array.isArray(body.data)
          ? body.data
          : body.data?.items || body.data || [];
        setTemplates(items);
        setTotal(body.total || items.length);
      }
    } catch (err) {
      message.error(extractErrorDetail(err, "加载模板失败"));
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, search, category, tag, message]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    // Fetch categories once.
    workflowTemplateApi
      .categories()
      .then((res) => {
        const body: any = res.data;
        if (body.code === 200 && Array.isArray(body.data)) {
          setCategories(body.data);
        }
      })
      .catch(() => {
        // Non-fatal: the dropdown is empty and the user can still
        // filter by typing in the search box.
      });
  }, []);

  const handleImport = async (template: WorkflowTemplate) => {
    setImporting(true);
    try {
      const res = await workflowTemplateApi.import(template.id);
      const body: any = res.data;
      if (body.code === 200) {
        const result: ImportResult = body.data;
        message.success(`已导入为「${result.name}」`);
        setImportTarget(null);
        router.push(`/dashboard/workflow?selected=${result.workflow_id}`);
      } else {
        message.error(body.message || "导入失败");
      }
    } catch (err) {
      message.error(extractErrorDetail(err, "导入失败"));
    } finally {
      setImporting(false);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 16,
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <h2 style={{ margin: 0 }}>工作流模板中心</h2>
        {/* M30 ship follow-up (2026-06-18): templates was previously
            nested under 工作流 in the sidebar, which AntD ProLayout
            treats as a collapse toggle. The sidebar now exposes 模板
            中心 as a sibling entry, so this in-page link is the
            direct way to get back to the workflow list without going
            through the sidebar. */}
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() => router.push("/dashboard/workflow")}
        >
          返回工作流列表
        </Button>
      </div>
      <Space wrap style={{ marginBottom: 16 }}>
        <Input
          placeholder="搜索模板"
          allowClear
          prefix={<SearchOutlined />}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 280 }}
        />
        <Select
          placeholder="分类"
          allowClear
          value={category}
          onChange={setCategory}
          style={{ width: 160 }}
          options={categories.map((c) => ({
            label: `${c.value} (${c.count})`,
            value: c.value,
          }))}
        />
        <Input
          placeholder="标签 (如 rag)"
          allowClear
          value={tag}
          onChange={(e) => setTag(e.target.value || undefined)}
          style={{ width: 180 }}
        />
        <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>
          刷新
        </Button>
      </Space>

      <Row gutter={[16, 16]}>
        {templates.map((t) => (
          <Col xs={24} sm={12} md={8} lg={6} key={t.id}>
            <TemplateCard
              template={t}
              onPreview={(id) => setPreviewId(id)}
              onImport={(id) => {
                const found = templates.find((x) => x.id === id);
                if (found) setImportTarget(found);
              }}
            />
          </Col>
        ))}
        {!loading && templates.length === 0 && (
          <Col span={24}>
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                <div>
                  <div style={{ fontSize: 16, marginBottom: 8 }}>暂无模板</div>
                  <div style={{ color: "#999", fontSize: 13 }}>
                    模板市场是跨租户共享的: 您发布的工作流模板,其他租户可以一键导入复用。
                  </div>
                </div>
              }
              style={{ padding: "48px 0" }}
            >
              <Space>
                <Button
                  type="primary"
                  icon={<ImportOutlined />}
                  onClick={() => router.push("/dashboard/workflow")}
                >
                  去发布第一个模板
                </Button>
                <Button onClick={refresh}>刷新试试</Button>
              </Space>
            </Empty>
          </Col>
        )}
      </Row>

      <TemplatePreview
        templateId={previewId}
        onClose={() => setPreviewId(null)}
      />

      <Modal
        title="导入模板"
        open={importTarget !== null}
        onCancel={() => setImportTarget(null)}
        confirmLoading={importing}
        onOk={async () => {
          if (importTarget) await handleImport(importTarget);
        }}
        okText="确认导入"
        cancelText="取消"
        okButtonProps={{ icon: <ImportOutlined /> }}
      >
        {importTarget && (
          <p>
            将导入模板 <strong>{importTarget.name}</strong> 到我的工作流?
            <br />
            <span style={{ color: "#888", fontSize: 12 }}>
              导入后会在工作流列表新增一条记录，名字为「{importTarget.name}」。
            </span>
          </p>
        )}
      </Modal>
    </div>
  );
}
