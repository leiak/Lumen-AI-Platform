"use client";

// M35: /dashboard/system/playbooks — Playbook 管理页
// 列表 + 创建/编辑/删除(built-in 保护)+ YAML 导入。
// 用 App.useApp() 模式显示 toast(MEMORY 2026-06-07:静态 message API
// 在 Next.js 15 strict mode 下不渲染)。

import { useEffect, useState, useCallback } from "react";
import {
  Table,
  Button,
  Space,
  Modal,
  Form,
  Input,
  Select,
  App,
  Popconfirm,
  Tag,
  Card,
  Empty,
  Spin,
  Alert,
  Tooltip,
} from "antd";
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ImportOutlined,
  ReloadOutlined,
  LockOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import {
  listPlaybooks,
  createPlaybook,
  updatePlaybook,
  deletePlaybook,
  importPlaybookYaml,
  getPlaybook,
} from "@/services/playbook";
import type { PlaybookListItem, PlaybookDetail } from "@/types/playbook";

const { TextArea } = Input;

interface FormValues {
  name: string;
  description?: string;
  scope?: string[];
  yaml_content: string;
}

const DEFAULT_YAML = `# 在这里粘贴你的 playbook YAML
# 必填字段(至少一个): keywords / palette / avoid / voice_direction

keywords:
  - clean
  - professional
  - modern

palette:
  primary: ["#0F4C81", "#3B7BB5"]
  background: ["#FFFFFF"]

voice_direction: calm, clear, neutral
scope: [image, tts]
`;

export default function PlaybooksPage() {
  const { message } = App.useApp();
  const [items, setItems] = useState<PlaybookListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [modalOpen, setModalOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [editing, setEditing] = useState<PlaybookDetail | null>(null);
  const [form] = Form.useForm<FormValues>();
  const [importForm] = Form.useForm<FormValues>();

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listPlaybooks({ page, page_size: pageSize });
      setItems(res.items);
      setTotal(res.total);
    } catch (e) {
      message.error(`加载失败: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, message]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({
      name: "",
      description: "",
      scope: ["image", "tts"],
      yaml_content: DEFAULT_YAML,
    });
    setModalOpen(true);
  };

  const openEdit = async (row: PlaybookListItem) => {
    if (row.is_builtin) {
      message.warning("内置 playbook 不可编辑");
      return;
    }
    try {
      const detail = await getPlaybook(row.id);
      setEditing(detail);
      form.setFieldsValue({
        name: detail.name,
        description: detail.description ?? "",
        scope: detail.scope ?? ["image", "tts"],
        yaml_content: detail.yaml_content,
      });
      setModalOpen(true);
    } catch (e) {
      message.error(`加载详情失败: ${(e as Error).message}`);
    }
  };

  const onSubmit = async () => {
    const values = await form.validateFields();
    try {
      if (editing) {
        await updatePlaybook(editing.id, {
          description: values.description,
          scope: values.scope,
          yaml_content: values.yaml_content,
        });
        message.success("已保存");
      } else {
        await createPlaybook({
          name: values.name,
          description: values.description,
          scope: values.scope,
          yaml_content: values.yaml_content,
        });
        message.success("已创建");
      }
      setModalOpen(false);
      void reload();
    } catch (e) {
      message.error(`保存失败: ${(e as Error).message}`);
    }
  };

  const onImport = async () => {
    const values = await importForm.validateFields();
    try {
      await importPlaybookYaml({
        name: values.name,
        description: values.description,
        scope: values.scope,
        yaml_content: values.yaml_content,
      });
      message.success("已导入");
      setImportOpen(false);
      void reload();
    } catch (e) {
      message.error(`导入失败: ${(e as Error).message}`);
    }
  };

  const onDelete = async (row: PlaybookListItem) => {
    if (row.is_builtin) {
      message.warning("内置 playbook 不可删除");
      return;
    }
    try {
      await deletePlaybook(row.id);
      message.success("已删除");
      void reload();
    } catch (e) {
      message.error(`删除失败: ${(e as Error).message}`);
    }
  };

  const columns: ColumnsType<PlaybookListItem> = [
    {
      title: "ID",
      dataIndex: "id",
      width: 60,
    },
    {
      title: "名称",
      dataIndex: "name",
      render: (v: string, row) => (
        <Space>
          <span>{v}</span>
          {row.is_builtin && (
            <Tooltip title="内置 playbook,不可编辑 / 删除">
              <Tag color="blue" icon={<LockOutlined />}>内置</Tag>
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: "作用域",
      dataIndex: "scope",
      width: 180,
      render: (scopes: string[] | null) =>
        (scopes || []).map((s) => (
          <Tag key={s} color={s === "image" ? "purple" : s === "tts" ? "volcano" : "default"}>
            {s}
          </Tag>
        )),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 180,
      render: (v: string) => new Date(v).toLocaleString(),
    },
    {
      title: "操作",
      width: 200,
      render: (_, row) => (
        <Space>
          <Button
            size="small"
            icon={<EditOutlined />}
            disabled={row.is_builtin}
            onClick={() => void openEdit(row)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除该 playbook?"
            disabled={row.is_builtin}
            onConfirm={() => void onDelete(row)}
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              disabled={row.is_builtin}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={
          <Space>
            <span>风格 Playbook 管理</span>
            <Tag color="blue">M35</Tag>
          </Space>
        }
        extra={
          <Space>
            <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>
              导入 YAML
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              新建 Playbook
            </Button>
            <Button icon={<ReloadOutlined />} onClick={() => void reload()}>
              刷新
            </Button>
          </Space>
        }
      >
        <Alert
          style={{ marginBottom: 16 }}
          type="info"
          showIcon
          message="Playbook 把视觉/语音风格 token 注入到图片生成 prompt 与 TTS 语音方向。内置 5 个(clean-professional / anime-ghibli / cinematic-dark / tech-minimalist / warm-storytelling)只读,可在自定义 playbook 基础上扩展。"
        />
        <Spin spinning={loading}>
          {items.length === 0 && !loading ? (
            <Empty description="暂无 playbook" />
          ) : (
            <Table
              rowKey="id"
              columns={columns}
              dataSource={items}
              pagination={{
                current: page,
                pageSize,
                total,
                onChange: (p) => setPage(p),
              }}
            />
          )}
        </Spin>
      </Card>

      {/* Create / Edit Modal */}
      <Modal
        title={editing ? `编辑: ${editing.name}` : "新建 Playbook"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void onSubmit()}
        width={720}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, max: 100 }]}
          >
            <Input
              placeholder="clean-professional"
              disabled={!!editing}
            />
          </Form.Item>
          <Form.Item name="description" label="描述" rules={[{ max: 2000 }]}>
            <Input placeholder="一句话描述这个 playbook 的风格" />
          </Form.Item>
          <Form.Item name="scope" label="作用域" tooltip="该 playbook 可以用于哪些创作目标">
            <Select mode="multiple" placeholder="image / tts / video">
              <Select.Option value="image">image</Select.Option>
              <Select.Option value="tts">tts</Select.Option>
              <Select.Option value="video">video (M36+)</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item
            name="yaml_content"
            label="YAML 内容"
            rules={[{ required: true, min: 1 }]}
            tooltip="至少包含 keywords / palette / avoid / voice_direction 其一"
          >
            <TextArea rows={14} style={{ fontFamily: "monospace" }} />
          </Form.Item>
        </Form>
      </Modal>

      {/* Import YAML Modal */}
      <Modal
        title="导入 Playbook YAML"
        open={importOpen}
        onCancel={() => setImportOpen(false)}
        onOk={() => void onImport()}
        okText="导入"
        cancelText="取消"
      >
        <Form form={importForm} layout="vertical" preserve={false}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="my-style" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input />
          </Form.Item>
          <Form.Item name="scope" label="作用域" initialValue={["image", "tts"]}>
            <Select mode="multiple">
              <Select.Option value="image">image</Select.Option>
              <Select.Option value="tts">tts</Select.Option>
              <Select.Option value="video">video (M36+)</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="yaml_content" label="YAML" rules={[{ required: true }]}>
            <TextArea rows={12} style={{ fontFamily: "monospace" }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
