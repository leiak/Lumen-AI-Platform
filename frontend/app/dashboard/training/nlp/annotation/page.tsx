"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  message,
  Popconfirm,
  Card,
  Space,
  Select,
  Tag,
  Empty,
  Alert,
} from "antd";
import {
  PlusOutlined,
  UploadOutlined,
  FileTextOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  nlpApi,
  NLPAnnotation,
  NLPClassification,
  parseDatasetText,
  ParsedDatasetRow,
} from "@/services/nlp";

const PREVIEW_ROW_LIMIT = 5;

export default function NLPAnnotationPage() {
  const [annotations, setAnnotations] = useState<NLPAnnotation[]>([]);
  const [classifications, setClassifications] = useState<NLPClassification[]>([]);
  const [filterClassification, setFilterClassification] = useState<number | undefined>();
  const [loading, setLoading] = useState(false);
  // Server total for the local-paged annotation list.
  const [total, setTotal] = useState(0);
  const [createVisible, setCreateVisible] = useState(false);
  const [importVisible, setImportVisible] = useState(false);
  const [importing, setImporting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [createForm] = Form.useForm();

  // Bulk import state (client-side parsed preview)
  const [bulkText, setBulkText] = useState("");
  const [defaultClassificationId, setDefaultClassificationId] = useState<number | undefined>();
  const [parsedRows, setParsedRows] = useState<ParsedDatasetRow[]>([]);

  const fetchClassifications = async () => {
    try {
      const response = await nlpApi.listClassifications(1, 100);
      if (response.data.code === 200) {
        setClassifications(response.data.data || []);
      }
    } catch (error) {
      message.error("获取分类列表失败");
    }
  };

  const fetchAnnotations = async () => {
    setLoading(true);
    try {
      const response = await nlpApi.listAnnotations(filterClassification, 1, 200);
      if (response.data.code === 200) {
        setAnnotations(response.data.data || []);
        // Surface the real server total even though the local Table only
        // shows one page worth of data.
        setTotal(response.data.total || (response.data.data || []).length);
      }
    } catch (error) {
      message.error("获取文本数据集失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchClassifications();
  }, []);

  useEffect(() => {
    fetchAnnotations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterClassification]);

  const classificationName = (id: number) =>
    classifications.find((c) => c.id === id)?.name || `#${id}`;

  const handleCreate = async (values: any) => {
    setSubmitting(true);
    try {
      const response = await nlpApi.createAnnotation(values);
      if (response.data.code === 200) {
        message.success("添加成功");
        setCreateVisible(false);
        createForm.resetFields();
        fetchAnnotations();
      }
    } catch (error) {
      message.error("添加失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const response = await nlpApi.deleteAnnotation(id);
      if (response.data.code === 200) {
        message.success("删除成功");
        fetchAnnotations();
      }
    } catch (error) {
      message.error("删除失败");
    }
  };

  const handleBulkImport = async () => {
    if (parsedRows.length === 0) {
      message.warning("请粘贴或上传至少一条文本数据");
      return;
    }
    if (!defaultClassificationId && parsedRows.some((r) => !r.classification_id)) {
      message.warning("请选择默认分类（用于没有标签的文本行）");
      return;
    }
    setImporting(true);
    let successCount = 0;
    let failCount = 0;
    for (const row of parsedRows) {
      const classification_id = row.classification_id ?? defaultClassificationId;
      if (!classification_id) {
        failCount += 1;
        continue;
      }
      try {
        const resp = await nlpApi.createAnnotation({
          content: row.content,
          classification_id,
        });
        if (resp.data?.code === 200) {
          successCount += 1;
        } else {
          failCount += 1;
        }
      } catch {
        failCount += 1;
      }
    }
    setImporting(false);
    message.success(`导入完成：成功 ${successCount}，失败 ${failCount}`);
    setBulkText("");
    setParsedRows([]);
    setImportVisible(false);
    fetchAnnotations();
  };

  const previewRows = useMemo(
    () => parsedRows.slice(0, PREVIEW_ROW_LIMIT),
    [parsedRows]
  );

  const columns = [
    { title: "ID", dataIndex: "id", key: "id", width: 60 },
    {
      title: "文本",
      dataIndex: "content",
      key: "content",
      ellipsis: true,
      render: (text: string) => (
        <span title={text}>
          <FileTextOutlined style={{ marginRight: 6, color: "#1677ff" }} />
          {text}
        </span>
      ),
    },
    {
      title: "所属分类",
      dataIndex: "classification_id",
      key: "classification_id",
      width: 160,
      render: (id: number) => <Tag color="blue">{classificationName(id)}</Tag>,
    },
    { title: "创建时间", dataIndex: "created_at", key: "created_at", width: 180 },
    {
      title: "操作",
      key: "action",
      width: 100,
      render: (_: any, record: NLPAnnotation) => (
        <Popconfirm title="确认删除?" onConfirm={() => handleDelete(record.id)}>
          <Button size="small" danger>
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Card
        title="文本数据集管理"
        extra={
          <Space>
            <Select
              placeholder="按分类筛选"
              allowClear
              style={{ width: 200 }}
              value={filterClassification}
              onChange={(v) => setFilterClassification(v)}
              options={classifications.map((c) => ({ value: c.id, label: c.name }))}
            />
            <Button
              icon={<UploadOutlined />}
              onClick={() => {
                setImportVisible(true);
                setBulkText("");
                setParsedRows([]);
                setDefaultClassificationId(filterClassification);
              }}
            >
              批量导入
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setCreateVisible(true)}
            >
              新增文本
            </Button>
          </Space>
        }
      >
        <Table
          columns={columns}
          dataSource={annotations}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 10, total, showTotal: (t) => `共 ${t} 条` }}
        />
      </Card>

      {/* Create single annotation */}
      <Modal
        title="新增文本数据"
        open={createVisible}
        onCancel={() => {
          setCreateVisible(false);
          createForm.resetFields();
        }}
        footer={null}
      >
        <Form form={createForm} layout="vertical" onFinish={handleCreate}>
          <Form.Item
            name="content"
            label="文本内容"
            rules={[{ required: true, message: "请输入文本" }]}
          >
            <Input.TextArea rows={4} placeholder="请输入训练文本" />
          </Form.Item>
          <Form.Item
            name="classification_id"
            label="所属分类"
            rules={[{ required: true, message: "请选择分类" }]}
          >
            <Select
              placeholder="选择分类"
              options={classifications.map((c) => ({ value: c.id, label: c.name }))}
            />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={submitting}>
                添加
              </Button>
              <Button onClick={() => setCreateVisible(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* Bulk import modal */}
      <Modal
        title="批量导入文本数据集"
        open={importVisible}
        width={780}
        onCancel={() => {
          if (!importing) setImportVisible(false);
        }}
        footer={[
          <Button key="cancel" onClick={() => setImportVisible(false)} disabled={importing}>
            取消
          </Button>,
          <Button
            key="import"
            type="primary"
            icon={<ThunderboltOutlined />}
            loading={importing}
            onClick={handleBulkImport}
          >
            导入 {parsedRows.length > 0 ? `(${parsedRows.length})` : ""}
          </Button>,
        ]}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="支持 CSV / TSV / 一行一条 文本。可选表头：text, label（label 留空时使用下方默认分类）。"
        />
        <Form layout="vertical">
          <Form.Item label="默认分类（用于没有 label 列的行）" required>
            <Select
              placeholder="选择默认分类"
              value={defaultClassificationId}
              onChange={(v) => {
                setDefaultClassificationId(v);
                setParsedRows(parseDatasetText(bulkText, v));
              }}
              options={classifications.map((c) => ({ value: c.id, label: c.name }))}
            />
          </Form.Item>
          <Form.Item label="文本内容">
            <Input.TextArea
              rows={8}
              value={bulkText}
              onChange={(e) => {
                const v = e.target.value;
                setBulkText(v);
                setParsedRows(parseDatasetText(v, defaultClassificationId));
              }}
              placeholder={
                "例如:\n你好世界,1\n今天天气不错,2\n或者带表头:\ntext,label\n你好世界,1\n今天天气不错,2"
              }
            />
          </Form.Item>
          <div style={{ marginBottom: 8 }}>
            <Space>
              <Tag color="blue">解析到 {parsedRows.length} 条</Tag>
              {parsedRows.length > PREVIEW_ROW_LIMIT && (
                <Tag>仅预览前 {PREVIEW_ROW_LIMIT} 条</Tag>
              )}
            </Space>
          </div>
          {previewRows.length > 0 ? (
            <Table
              size="small"
              pagination={false}
              rowKey={(_r, idx) => String(idx)}
              dataSource={previewRows}
              columns={[
                {
                  title: "#",
                  key: "idx",
                  width: 50,
                  render: (_r, _r2, idx: number) => idx + 1,
                },
                {
                  title: "文本",
                  dataIndex: "content",
                  ellipsis: true,
                },
                {
                  title: "分类ID",
                  dataIndex: "classification_id",
                  width: 100,
                  render: (v?: number) =>
                    v ? <Tag>{v}</Tag> : <Tag color="orange">使用默认</Tag>,
                },
              ]}
            />
          ) : (
            <Empty description="暂无预览" />
          )}
        </Form>
      </Modal>
    </div>
  );
}
