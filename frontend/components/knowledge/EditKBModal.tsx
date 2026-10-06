"use client";

import {
  Modal,
  Form,
  Input,
  Select,
  InputNumber,
  Slider,
  Collapse,
  Space,
  Button,
  Typography,
} from "antd";
import type { FormInstance } from "antd";

import EmbeddingModelSelect from "@/components/EmbeddingModelSelect";
import type { KnowledgeBase } from "@/types/api";

const { Text } = Typography;
const { Panel } = Collapse;

interface EditKBModalProps {
  editingKB: KnowledgeBase | null;
  open: boolean;
  editForm: FormInstance;
  editSearchWeights: {
    title: number;
    important_kw: number;
    question_kw: number;
    text: number;
  };
  setEditSearchWeights: (v: {
    title: number;
    important_kw: number;
    question_kw: number;
    text: number;
  }) => void;
  handleUpdate: (values: any) => Promise<void>;
  setEditModalVisible: (v: boolean) => void;
}

/**
 * 「编辑知识库」Modal —— 从 page.tsx 抽出。
 *
 * 由 useKnowledgeList hook 持有 editingKB / editModalVisible / editForm /
 * editSearchWeights / handleUpdate,本组件是纯 JSX 渲染层。
 * Embedding 模型创建后锁定(`disabled` prop),避免误改。
 */
export default function EditKBModal({
  editingKB,
  open,
  editForm,
  editSearchWeights,
  setEditSearchWeights,
  handleUpdate,
  setEditModalVisible,
}: EditKBModalProps) {
  return (
    <Modal
      title={`编辑知识库: ${editingKB?.name || ""}`}
      open={open}
      onCancel={() => {
        setEditModalVisible(false);
        editForm.resetFields();
      }}
      footer={null}
      width={600}
    >
      <Form form={editForm} layout="vertical" onFinish={handleUpdate}>
        <Form.Item
          name="name"
          label="名称"
          rules={[{ required: true, message: "请输入名称" }]}
        >
          <Input placeholder="请输入知识库名称" />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea placeholder="请输入描述" />
        </Form.Item>
        {/* Embedding 模型 — locked once a KB is created. The
            EmbeddingModelSelect renders the disabled hint itself
            when `disabled` is true. */}
        <Form.Item name="embedding_model_config_id" label="Embedding 模型">
          <EmbeddingModelSelect disabled />
        </Form.Item>
        {/* 默认解析器 */}
        <Form.Item name="default_parser" label="默认解析器">
          <Select>
            <Select.Option value="general">通用文档</Select.Option>
            <Select.Option value="paper">学术论文</Select.Option>
            <Select.Option value="qa">问答文档</Select.Option>
            <Select.Option value="table">表格文档</Select.Option>
            <Select.Option value="manual">用户手册</Select.Option>
            <Select.Option value="laws">法律文档</Select.Option>
          </Select>
        </Form.Item>
        {/* 分块大小和重叠 */}
        <Space>
          <Form.Item name="chunk_size" label="分块大小">
            <InputNumber min={100} max={2000} />
          </Form.Item>
          <Form.Item name="chunk_overlap" label="重叠token">
            <InputNumber min={0} max={200} />
          </Form.Item>
        </Space>
        {/* 搜索权重 Collapse */}
        <Collapse ghost>
          <Panel header="搜索权重配置" key="weights">
            <Space direction="vertical" style={{ width: "100%" }}>
              <div>
                <Text>title: {editSearchWeights.title}</Text>
                <Slider
                  min={0}
                  max={100}
                  value={editSearchWeights.title}
                  onChange={(v) =>
                    setEditSearchWeights({ ...editSearchWeights, title: v })
                  }
                />
              </div>
              <div>
                <Text>important_kw: {editSearchWeights.important_kw}</Text>
                <Slider
                  min={0}
                  max={100}
                  value={editSearchWeights.important_kw}
                  onChange={(v) =>
                    setEditSearchWeights({
                      ...editSearchWeights,
                      important_kw: v,
                    })
                  }
                />
              </div>
              <div>
                <Text>question_kw: {editSearchWeights.question_kw}</Text>
                <Slider
                  min={0}
                  max={100}
                  value={editSearchWeights.question_kw}
                  onChange={(v) =>
                    setEditSearchWeights({
                      ...editSearchWeights,
                      question_kw: v,
                    })
                  }
                />
              </div>
              <div>
                <Text>text: {editSearchWeights.text}</Text>
                <Slider
                  min={0}
                  max={100}
                  value={editSearchWeights.text}
                  onChange={(v) =>
                    setEditSearchWeights({ ...editSearchWeights, text: v })
                  }
                />
              </div>
            </Space>
          </Panel>
        </Collapse>
        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit">
              保存
            </Button>
            <Button onClick={() => setEditModalVisible(false)}>取消</Button>
          </Space>
        </Form.Item>
      </Form>
    </Modal>
  );
}