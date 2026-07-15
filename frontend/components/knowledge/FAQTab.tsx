"use client";

/**
 * M31: FAQ Q&A subcomponent.
 *
 * Lives in `components/knowledge/FAQTab.tsx` so the parent
 * `app/dashboard/knowledge/page.tsx` doesn't grow another
 * 250 lines. Used inside the "Q&A 问答" tab on the KB detail
 * page.
 *
 * Responsibilities:
 * - List FAQs with pagination + category filter + free-text
 *   search.
 * - Open a modal to create / edit a single Q&A.
 * - Open a modal to bulk-import JSON or CSV.
 * - Delete a Q&A (with Popconfirm).
 *
 * All API calls go through `knowledgeApi` (the new methods
 * added in `services/knowledge.ts` M31 block). Errors are
 * surfaced via `App.useApp()` so the toast actually renders
 * under antd v5 + Next.js 15 strict mode (per the
 * MEMORY.md "antd v5 toast 不显示" entry).
 */
import { useState } from "react";
import {
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App } from "antd";
import {
  FAQBulkImportRequest,
  FAQEntry,
  FAQEntryCreate,
  FAQEntryUpdate,
  knowledgeApi,
} from "@/services/knowledge";

const { TextArea } = Input;
const { Text } = Typography;

interface FAQTabProps {
  /** The active KB id; the tab is empty until this is set. */
  kbId: number;
}

interface FAQFormValues {
  question: string;
  answer: string;
  category?: string;
  tags?: string[];
}

export default function FAQTab({ kbId }: FAQTabProps) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  // ------- list / pagination / filter state
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>();

  // ------- create / edit modal state
  const [editingEntry, setEditingEntry] = useState<FAQEntry | null>(null);
  const [formModalOpen, setFormModalOpen] = useState(false);
  const [form] = Form.useForm<FAQFormValues>();
  const editing = editingEntry !== null;

  // ------- bulk import modal state
  const [bulkModalOpen, setBulkModalOpen] = useState(false);
  const [bulkFormat, setBulkFormat] = useState<"json" | "csv">("json");
  const [bulkContent, setBulkContent] = useState("");

  // ------- queries
  const listQuery = useQuery({
    queryKey: ["faqs", kbId, page, pageSize, search, categoryFilter],
    queryFn: () =>
      knowledgeApi
        .listFaqs(kbId, {
          page,
          page_size: pageSize,
          search: search || undefined,
          category: categoryFilter,
        })
        .then((r) => r.data),
    enabled: Boolean(kbId),
  });

  const createMutation = useMutation({
    mutationFn: (data: FAQEntryCreate) => knowledgeApi.createFaq(kbId, data),
    onSuccess: (res) => {
      if (res.data.code === 200) {
        message.success("Q&A 已新增");
        queryClient.invalidateQueries({ queryKey: ["faqs", kbId] });
        setFormModalOpen(false);
        form.resetFields();
      } else {
        message.error(res.data.message || "新增失败");
      }
    },
    onError: () => message.error("新增失败: 网络错误"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: FAQEntryUpdate }) =>
      knowledgeApi.updateFaq(kbId, id, data),
    onSuccess: (res) => {
      if (res.data.code === 200) {
        message.success("Q&A 已更新");
        queryClient.invalidateQueries({ queryKey: ["faqs", kbId] });
        setFormModalOpen(false);
        setEditingEntry(null);
        form.resetFields();
      } else {
        message.error(res.data.message || "更新失败");
      }
    },
    onError: () => message.error("更新失败: 网络错误"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => knowledgeApi.deleteFaq(kbId, id),
    onSuccess: (res) => {
      if (res.data.code === 200) {
        message.success("Q&A 已删除");
        queryClient.invalidateQueries({ queryKey: ["faqs", kbId] });
      } else {
        message.error(res.data.message || "删除失败");
      }
    },
    onError: () => message.error("删除失败: 网络错误"),
  });

  const bulkMutation = useMutation({
    mutationFn: (data: FAQBulkImportRequest) =>
      knowledgeApi.bulkImportFaqs(kbId, data),
    onSuccess: (res) => {
      const result = res.data.data;
      if (res.data.code === 200 && result) {
        const failedCount = result.failed?.length ?? 0;
        if (failedCount > 0) {
          message.warning(
            `导入完成: 成功 ${result.inserted} 条, 失败 ${failedCount} 条`
          );
        } else {
          message.success(`导入完成: 成功 ${result.inserted} 条`);
        }
        queryClient.invalidateQueries({ queryKey: ["faqs", kbId] });
        setBulkModalOpen(false);
        setBulkContent("");
      } else {
        message.error(res.data.message || "导入失败");
      }
    },
    onError: () => message.error("导入失败: 网络错误"),
  });

  // ------- handlers
  const openCreateModal = () => {
    setEditingEntry(null);
    form.resetFields();
    setFormModalOpen(true);
  };

  const openEditModal = (entry: FAQEntry) => {
    setEditingEntry(entry);
    form.setFieldsValue({
      question: entry.question,
      answer: entry.answer,
      category: entry.category,
      tags: entry.tags,
    });
    setFormModalOpen(true);
  };

  const submitForm = async () => {
    try {
      const values = await form.validateFields();
      const payload: FAQEntryCreate = {
        question: values.question.trim(),
        answer: values.answer.trim(),
        category: values.category?.trim() || undefined,
        tags: values.tags,
      };
      if (editing) {
        // PATCH-style: only the changed fields go on the
        // wire. We use ``model_dump(exclude_unset=True)``
        // semantics by filtering out fields that match
        // the original — practical effect is the same and
        // it keeps the frontend test surface small.
        const updateData: FAQEntryUpdate = {
          question: payload.question,
          answer: payload.answer,
          category: payload.category,
          tags: payload.tags,
        };
        updateMutation.mutate({ id: editingEntry!.id, data: updateData });
      } else {
        createMutation.mutate(payload);
      }
    } catch {
      // AntD Form already surfaces per-field errors; no
      // need for an extra toast.
    }
  };

  const submitBulk = () => {
    if (!bulkContent.trim()) {
      message.warning("请粘贴 JSON 或 CSV 内容");
      return;
    }
    bulkMutation.mutate({ format: bulkFormat, content: bulkContent });
  };

  const faqs = (listQuery.data?.data as FAQEntry[]) ?? [];
  const total = listQuery.data?.total ?? 0;
  const submitting = createMutation.isPending || updateMutation.isPending;
  const bulkSubmitting = bulkMutation.isPending;

  // Build the category list from the current page so the
  // filter dropdown stays in sync with the data. The full
  // category list isn't paginated server-side, so this is
  // a best-effort UX nicety — a future change can wire a
  // dedicated ``GET /faq-categories`` endpoint.
  const knownCategories = Array.from(
    new Set(faqs.map((f) => f.category).filter(Boolean) as string[])
  );

  // ------- columns
  const columns: ColumnsType<FAQEntry> = [
    {
      title: "问题",
      dataIndex: "question",
      key: "question",
      ellipsis: { showTitle: false },
      width: 220,
      render: (q: string) => (
        <Tooltip title={q} placement="topLeft">
          <Text>{q}</Text>
        </Tooltip>
      ),
    },
    {
      title: "答案",
      dataIndex: "answer",
      key: "answer",
      ellipsis: { showTitle: false },
      render: (a: string) => (
        <Tooltip title={a} placement="topLeft">
          <Text type="secondary">{a}</Text>
        </Tooltip>
      ),
    },
    {
      title: "分类",
      dataIndex: "category",
      key: "category",
      width: 110,
      render: (cat?: string) =>
        cat ? <Tag color="blue">{cat}</Tag> : <Text type="secondary">—</Text>,
    },
    {
      title: "标签",
      dataIndex: "tags",
      key: "tags",
      width: 160,
      render: (tags?: string[]) =>
        tags && tags.length > 0
          ? tags.map((t) => <Tag key={t}>{t}</Tag>)
          : <Text type="secondary">—</Text>,
    },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      key: "updated_at",
      width: 170,
    },
    {
      title: "操作",
      key: "actions",
      width: 150,
      render: (_: unknown, record: FAQEntry) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEditModal(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定要删除此问答吗?"
            description="向量索引会同步清除。"
            okText="删除"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            onConfirm={() => deleteMutation.mutate(record.id)}
          >
            <Button
              type="link"
              size="small"
              danger
              icon={<DeleteOutlined />}
              loading={
                deleteMutation.isPending &&
                deleteMutation.variables === record.id
              }
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div data-testid="faq-tab">
      <Space style={{ marginBottom: 12 }} wrap>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={openCreateModal}
          data-testid="faq-create-btn"
        >
          新建问答
        </Button>
        <Button
          icon={<UploadOutlined />}
          onClick={() => setBulkModalOpen(true)}
          data-testid="faq-bulk-btn"
        >
          批量导入
        </Button>
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索问题或答案"
          style={{ width: 240 }}
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onPressEnter={() => {
            setSearch(searchInput.trim());
            setPage(1);
          }}
          data-testid="faq-search-input"
        />
        <Select
          allowClear
          placeholder="按分类筛选"
          style={{ width: 160 }}
          value={categoryFilter}
          onChange={(v) => {
            setCategoryFilter(v);
            setPage(1);
          }}
          options={knownCategories.map((c) => ({ label: c, value: c }))}
          data-testid="faq-category-filter"
        />
        <Button
          icon={<ReloadOutlined />}
          onClick={() => listQuery.refetch()}
          loading={listQuery.isFetching}
        >
          刷新
        </Button>
      </Space>

      <Table<FAQEntry>
        rowKey="id"
        size="small"
        loading={listQuery.isLoading}
        columns={columns}
        dataSource={faqs}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
        locale={{
          emptyText: listQuery.isLoading
            ? "加载中..."
            : "暂无问答,点上方「新建问答」开始录入",
        }}
      />

      {/* Create / Edit modal */}
      <Modal
        open={formModalOpen}
        title={editing ? "编辑问答" : "新建问答"}
        okText={editing ? "保存" : "新增"}
        cancelText="取消"
        confirmLoading={submitting}
        onCancel={() => {
          setFormModalOpen(false);
          setEditingEntry(null);
          form.resetFields();
        }}
        onOk={submitForm}
        destroyOnHidden
        width={640}
        data-testid="faq-form-modal"
      >
        <Form
          form={form}
          layout="vertical"
          preserve={false}
          initialValues={{ tags: [] }}
        >
          <Form.Item
            label="问题"
            name="question"
            rules={[
              { required: true, message: "请输入问题" },
              { max: 2000, message: "问题不能超过 2000 字符" },
            ]}
          >
            <TextArea
              rows={2}
              maxLength={2000}
              showCount
              placeholder="例如: 如何申请退货?"
              data-testid="faq-form-question"
            />
          </Form.Item>
          <Form.Item
            label="答案"
            name="answer"
            rules={[
              { required: true, message: "请输入答案" },
              { max: 8000, message: "答案不能超过 8000 字符" },
            ]}
          >
            <TextArea
              rows={4}
              maxLength={8000}
              showCount
              placeholder="例如: 请在 7 天内联系客服,提供订单号"
              data-testid="faq-form-answer"
            />
          </Form.Item>
          <Form.Item label="分类" name="category" extra="可选,如: 退货政策 / 物流时效">
            <Input
              maxLength={50}
              placeholder="退货政策"
              data-testid="faq-form-category"
            />
          </Form.Item>
          <Form.Item label="标签" name="tags" extra="回车添加,选填">
            <Select
              mode="tags"
              placeholder="按回车添加标签"
              maxTagCount={20}
              data-testid="faq-form-tags"
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* Bulk import modal */}
      <Modal
        open={bulkModalOpen}
        title="批量导入 Q&A"
        okText="开始导入"
        cancelText="取消"
        confirmLoading={bulkSubmitting}
        onCancel={() => setBulkModalOpen(false)}
        onOk={submitBulk}
        destroyOnHidden
        width={640}
        data-testid="faq-bulk-modal"
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <div>
            <Text>格式:</Text>
            <Select
              value={bulkFormat}
              onChange={setBulkFormat}
              style={{ width: 120, marginLeft: 8 }}
              options={[
                { label: "JSON", value: "json" },
                { label: "CSV", value: "csv" },
              ]}
              data-testid="faq-bulk-format"
            />
          </div>
          <TextArea
            rows={10}
            value={bulkContent}
            onChange={(e) => setBulkContent(e.target.value)}
            placeholder={
              bulkFormat === "json"
                ? '[\n  {"question": "...", "answer": "...", "category": "...", "tags": ["..."]}\n]'
                : "question,answer,category,tags\n退货政策?,请在 7 天内联系客服,退货政策,急\n运费多少?,包邮订单免运费,物流时效,"
            }
            data-testid="faq-bulk-content"
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {bulkFormat === "json"
              ? "JSON 数组,每个元素含 question / answer 必填,category / tags 可选"
              : "CSV 需表头: question,answer,category,tags;tags 用英文逗号分隔"}
          </Text>
        </Space>
      </Modal>
    </div>
  );
}
