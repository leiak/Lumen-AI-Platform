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
import type { ModelConfig } from "@/services/models";

const { Text } = Typography;
const { Panel } = Collapse;

interface CreateKBModalProps {
  open: boolean;
  form: FormInstance;
  searchWeights: {
    title: number;
    important_kw: number;
    question_kw: number;
    text: number;
  };
  setSearchWeights: (v: {
    title: number;
    important_kw: number;
    question_kw: number;
    text: number;
  }) => void;
  handleCreate: (values: any) => Promise<void>;
  setModalVisible: (v: boolean) => void;
  /** EmbeddingModelSelect.onLoaded 推上来的 model_configs 缓存;
   *  useKnowledgeList 通过 args.loadedEmbeddingModels 读,form auto-default 用。 */
  setLoadedEmbeddingModels: (models: ModelConfig[]) => void;
}

/**
 * 「创建知识库」Modal —— 从 page.tsx 抽出。
 *
 * 由 useKnowledgeList hook 持有 modalVisible / form / searchWeights /
 * handleCreate,本组件是纯 JSX 渲染层,所有状态通过 props 传入。
 */
export default function CreateKBModal({
  open,
  form,
  searchWeights,
  setSearchWeights,
  handleCreate,
  setModalVisible,
  setLoadedEmbeddingModels,
}: CreateKBModalProps) {
  return (
    <Modal
      title="创建知识库"
      open={open}
      onCancel={() => {
        setModalVisible(false);
        form.resetFields();
      }}
      footer={null}
    >
      <Form form={form} layout="vertical" onFinish={handleCreate}>
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
        {/* Embedding 模型 — sourced from model_configs (T18 component),
            not hardcoded. `embedding_model_config_id` is the FK the
            backend now requires on create. `onLoaded` pushes the
            loaded list up so the useEffect above can auto-default
            the field when the modal opens. */}
        <Form.Item
          name="embedding_model_config_id"
          label="Embedding 模型"
          rules={[{ required: true, message: "请选择 Embedding 模型" }]}
        >
          <EmbeddingModelSelect onLoaded={setLoadedEmbeddingModels} />
        </Form.Item>
        {/* 默认解析器 */}
        <Form.Item name="default_parser" label="默认解析器" initialValue="general">
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
          <Form.Item name="chunk_size" label="分块大小" initialValue={500}>
            <InputNumber min={100} max={2000} />
          </Form.Item>
          <Form.Item name="chunk_overlap" label="重叠token" initialValue={50}>
            <InputNumber min={0} max={200} />
          </Form.Item>
        </Space>
        {/* 搜索权重 Collapse */}
        <Collapse ghost>
          <Panel header="搜索权重配置" key="weights">
            <Space direction="vertical" style={{ width: "100%" }}>
              <div>
                <Text>title: {searchWeights.title}</Text>
                <Slider
                  min={0}
                  max={100}
                  value={searchWeights.title}
                  onChange={(v) =>
                    setSearchWeights({ ...searchWeights, title: v })
                  }
                />
              </div>
              <div>
                <Text>important_kw: {searchWeights.important_kw}</Text>
                <Slider
                  min={0}
                  max={100}
                  value={searchWeights.important_kw}
                  onChange={(v) =>
                    setSearchWeights({ ...searchWeights, important_kw: v })
                  }
                />
              </div>
              <div>
                <Text>question_kw: {searchWeights.question_kw}</Text>
                <Slider
                  min={0}
                  max={100}
                  value={searchWeights.question_kw}
                  onChange={(v) =>
                    setSearchWeights({ ...searchWeights, question_kw: v })
                  }
                />
              </div>
              <div>
                <Text>text: {searchWeights.text}</Text>
                <Slider
                  min={0}
                  max={100}
                  value={searchWeights.text}
                  onChange={(v) =>
                    setSearchWeights({ ...searchWeights, text: v })
                  }
                />
              </div>
            </Space>
          </Panel>
        </Collapse>
        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit">
              创建
            </Button>
            <Button onClick={() => setModalVisible(false)}>取消</Button>
          </Space>
        </Form.Item>
      </Form>
    </Modal>
  );
}