"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  InputNumber,
  message,
  Popconfirm,
  Card,
  Space,
  Tag,
  Progress,
  Divider,
  Select,
  Alert,
  Empty,
} from "antd";
import {
  PlusOutlined,
  PlayCircleOutlined,
  ThunderboltOutlined,
  ExperimentOutlined,
  FileTextOutlined,
} from "@ant-design/icons";
import {
  nlpApi,
  NLPTrainingConfig,
  NLPAnnotation,
  NLPClassification,
  TrainResult,
  PredictResult,
} from "@/services/nlp";

const MODEL_OPTIONS = [
  { value: "tfidf-lr", label: "TF-IDF + LogisticRegression（默认）" },
  { value: "tfidf-svm", label: "TF-IDF + LinearSVC（仅展示）" },
];

const DATASET_PREVIEW_LIMIT = 5;

export default function NLPClassificationPage() {
  const [data, setData] = useState<NLPClassification[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [modalVisible, setModalVisible] = useState(false);
  const [trainingModalVisible, setTrainingModalVisible] = useState(false);
  const [predictModalVisible, setPredictModalVisible] = useState(false);
  const [datasetModalVisible, setDatasetModalVisible] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Training flow
  const [training, setTraining] = useState(false);
  const [trainProgress, setTrainProgress] = useState(0);
  const [trainResult, setTrainResult] = useState<TrainResult | null>(null);
  const [trainError, setTrainError] = useState<string | null>(null);

  // Dataset preview state
  const [datasetLoading, setDatasetLoading] = useState(false);
  const [datasetRows, setDatasetRows] = useState<NLPAnnotation[]>([]);

  const [selectedClassification, setSelectedClassification] = useState<NLPClassification | null>(null);
  const [predictText, setPredictText] = useState("");
  const [predictResult, setPredictResult] = useState<PredictResult | null>(null);

  const [form] = Form.useForm();
  const [configForm] = Form.useForm();

  const fetchData = async () => {
    setLoading(true);
    try {
      const response = await nlpApi.listClassifications(1, 100);
      if (response.data.code === 200) {
        setData(response.data.data || []);
        // Surface the real server total so the "共 N 条" footer reflects
        // the full count even though the local Table only shows one page.
        setTotal(response.data.total || (response.data.data || []).length);
      }
    } catch (error) {
      message.error("获取分类列表失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleCreate = async (values: any) => {
    setSubmitting(true);
    try {
      const dataToSend = { ...values };
      if (dataToSend.keywords && typeof dataToSend.keywords === "string") {
        dataToSend.keywords = (dataToSend.keywords as string)
          .split(",")
          .map((k: string) => k.trim())
          .filter((k: string) => k);
      }
      const response = await nlpApi.createClassification(dataToSend);
      if (response.data.code === 200) {
        message.success("创建成功");
        setModalVisible(false);
        form.resetFields();
        fetchData();
      }
    } catch (error) {
      message.error("创建失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    setSubmitting(true);
    try {
      const response = await nlpApi.deleteClassification(id);
      if (response.data.code === 200) {
        message.success("删除成功");
        fetchData();
      }
    } catch (error) {
      message.error("删除失败");
    } finally {
      setSubmitting(false);
    }
  };

  // Simulated progress polling (current backend train is synchronous).
  // Drives a progress bar while the request is in flight.
  useEffect(() => {
    if (!training) return;
    setTrainProgress(0);
    const interval = setInterval(() => {
      setTrainProgress((prev) => {
        // Cap at 95% — the real result will fill the remainder.
        if (prev >= 95) return prev;
        const next = prev + Math.max(2, Math.round((95 - prev) * 0.1));
        return Math.min(95, next);
      });
    }, 500);
    return () => clearInterval(interval);
  }, [training]);

  const handleTrain = async (classification: NLPClassification) => {
    setSelectedClassification(classification);
    setTrainingModalVisible(true);
    setTrainResult(null);
    setTrainError(null);
    setTrainProgress(0);

    // Pre-fill config form with sensible defaults
    configForm.setFieldsValue({
      model: "tfidf-lr",
      epochs: 10,
      batch_size: 32,
      learning_rate: 0.001,
      max_features: 1000,
      test_size: 0.2,
    });
  };

  const submitTrain = async () => {
    if (!selectedClassification) return;
    let cfg: NLPTrainingConfig = {};
    try {
      cfg = (await configForm.validateFields()) as NLPTrainingConfig;
    } catch {
      // validation error already shown by antd
      return;
    }

    setTraining(true);
    setTrainError(null);
    setTrainResult(null);
    try {
      const response = await nlpApi.train(selectedClassification.id, cfg);
      if (response.data?.code === 200 && response.data?.data) {
        setTrainResult(response.data.data as TrainResult);
        setTrainProgress(100);
        if ((response.data.data as TrainResult).status === "success") {
          message.success("训练完成");
        } else {
          message.warning((response.data.data as TrainResult).message || "训练未成功");
        }
      } else {
        setTrainError(response.data?.message || "训练失败");
        message.error(response.data?.message || "训练失败");
      }
    } catch (error: any) {
      const detail =
        error?.response?.data?.message ||
        error?.response?.data?.detail ||
        error?.message ||
        "训练失败";
      setTrainError(detail);
      message.error(detail);
    } finally {
      setTraining(false);
    }
  };

  const handlePredict = async () => {
    if (!selectedClassification || !predictText.trim()) {
      message.warning("请输入预测文本");
      return;
    }
    setSubmitting(true);
    try {
      const response = await nlpApi.predict(predictText, selectedClassification.id);
      if (response.data.code === 200) {
        setPredictResult(response.data.data);
      } else {
        message.error(response.data.message || "预测失败");
      }
    } catch (error: any) {
      message.error(error?.response?.data?.message || "预测失败");
    } finally {
      setSubmitting(false);
    }
  };

  const openPredictModal = (classification: NLPClassification) => {
    setSelectedClassification(classification);
    setPredictText("");
    setPredictResult(null);
    setPredictModalVisible(true);
  };

  const openDatasetModal = async (classification: NLPClassification) => {
    setSelectedClassification(classification);
    setDatasetModalVisible(true);
    setDatasetLoading(true);
    setDatasetRows([]);
    try {
      const response = await nlpApi.listAnnotations(classification.id, 1, 50);
      if (response.data.code === 200) {
        setDatasetRows(response.data.data || []);
      }
    } catch {
      message.error("获取数据集失败");
    } finally {
      setDatasetLoading(false);
    }
  };

  const datasetPreview = useMemo(
    () => datasetRows.slice(0, DATASET_PREVIEW_LIMIT),
    [datasetRows]
  );

  const columns = [
    { title: "ID", dataIndex: "id", key: "id", width: 60 },
    { title: "名称", dataIndex: "name", key: "name" },
    { title: "描述", dataIndex: "description", key: "description", ellipsis: true },
    {
      title: "关键词",
      dataIndex: "keywords",
      key: "keywords",
      render: (k: string[] = []) =>
        k.length > 0
          ? k.slice(0, 3).map((kw, i) => <Tag key={i}>{kw}</Tag>)
          : <Tag color="default">无</Tag>,
      width: 200,
    },
    { title: "创建时间", dataIndex: "created_at", key: "created_at", width: 180 },
    {
      title: "操作",
      key: "action",
      width: 320,
      render: (_: any, record: NLPClassification) => (
        <Space wrap>
          <Button
            size="small"
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={() => handleTrain(record)}
          >
            训练
          </Button>
          <Button
            size="small"
            icon={<ExperimentOutlined />}
            onClick={() => openDatasetModal(record)}
          >
            数据集
          </Button>
          <Button
            size="small"
            icon={<ThunderboltOutlined />}
            onClick={() => openPredictModal(record)}
          >
            预测
          </Button>
          <Popconfirm title="确认删除?" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger loading={submitting}>
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
        title="NLP 分类训练"
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setModalVisible(true)}
          >
            创建分类
          </Button>
        }
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="流程：先为分类添加文本数据集（“数据集”按钮可跳转到 /training/nlp/annotation 批量导入），再点击“训练”配置超参数并启动训练，训练完成后用“预测”验证效果。"
        />
        <Table
          columns={columns}
          dataSource={data}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 10, total, showTotal: (t) => `共 ${t} 条` }}
        />
      </Card>

      {/* Create Modal */}
      <Modal
        title="创建分类"
        open={modalVisible}
        onCancel={() => {
          setModalVisible(false);
          form.resetFields();
        }}
        footer={null}
      >
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input placeholder="请输入分类名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="请输入描述" />
          </Form.Item>
          <Form.Item name="keywords" label="关键词">
            <Input placeholder="多个关键词用逗号分隔" />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={submitting}>
                创建
              </Button>
              <Button onClick={() => setModalVisible(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* Training Modal */}
      <Modal
        title={`训练分类：${selectedClassification?.name || ""}`}
        open={trainingModalVisible}
        width={680}
        onCancel={() => {
          if (!training) {
            setTrainingModalVisible(false);
            setTrainResult(null);
            setTrainError(null);
            setTrainProgress(0);
          }
        }}
        footer={[
          <Button
            key="close"
            onClick={() => {
              setTrainingModalVisible(false);
              setTrainResult(null);
              setTrainError(null);
              setTrainProgress(0);
            }}
            disabled={training}
          >
            关闭
          </Button>,
          <Button
            key="submit"
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={training}
            onClick={submitTrain}
          >
            启动训练
          </Button>,
        ]}
      >
        <div style={{ padding: "8px 0" }}>
          <Card size="small" title="训练配置（超参数）">
            <Form form={configForm} layout="vertical">
              <Form.Item
                name="model"
                label="模型"
                rules={[{ required: true, message: "请选择模型" }]}
              >
                <Select options={MODEL_OPTIONS} />
              </Form.Item>
              <Space size="middle" style={{ display: "flex" }} wrap>
                <Form.Item
                  name="epochs"
                  label="Epochs"
                  style={{ minWidth: 140 }}
                  rules={[{ required: true, message: "请输入" }]}
                >
                  <InputNumber min={1} max={500} style={{ width: "100%" }} />
                </Form.Item>
                <Form.Item
                  name="batch_size"
                  label="Batch Size"
                  style={{ minWidth: 140 }}
                  rules={[{ required: true, message: "请输入" }]}
                >
                  <InputNumber min={1} max={1024} style={{ width: "100%" }} />
                </Form.Item>
                <Form.Item
                  name="learning_rate"
                  label="学习率"
                  style={{ minWidth: 160 }}
                  rules={[{ required: true, message: "请输入" }]}
                >
                  <InputNumber
                    min={0.000001}
                    max={1}
                    step={0.001}
                    style={{ width: "100%" }}
                  />
                </Form.Item>
              </Space>
              <Space size="middle" style={{ display: "flex" }} wrap>
                <Form.Item
                  name="max_features"
                  label="最大特征数 (TF-IDF)"
                  style={{ minWidth: 200 }}
                  rules={[{ required: true, message: "请输入" }]}
                >
                  <InputNumber min={100} max={50000} step={100} style={{ width: "100%" }} />
                </Form.Item>
                <Form.Item
                  name="test_size"
                  label="测试集比例"
                  style={{ minWidth: 160 }}
                  rules={[{ required: true, message: "请输入" }]}
                >
                  <InputNumber min={0.05} max={0.5} step={0.05} style={{ width: "100%" }} />
                </Form.Item>
              </Space>
            </Form>
          </Card>

          <Divider />

          {training ? (
            <div>
              <Progress percent={trainProgress} status="active" />
              <p style={{ textAlign: "center", color: "#1677ff" }}>
                正在训练模型，请稍候...
              </p>
            </div>
          ) : trainResult ? (
            <Card
              size="small"
              title={
                <Space>
                  <span>训练结果</span>
                  <Tag color={trainResult.status === "success" ? "green" : "red"}>
                    {trainResult.status}
                  </Tag>
                </Space>
              }
            >
              {trainResult.accuracy !== undefined && (
                <p>
                  <strong>准确率：</strong>
                  <Tag color="blue">{(trainResult.accuracy * 100).toFixed(2)}%</Tag>
                </p>
              )}
              {trainResult.model_path && (
                <p>
                  <strong>模型路径：</strong>
                  <code>{trainResult.model_path}</code>
                </p>
              )}
              {trainResult.metrics &&
                Object.entries(trainResult.metrics).map(([k, v]) => (
                  <p key={k}>
                    <strong>{k}：</strong>
                    <Tag color="purple">{typeof v === "number" ? v.toFixed(4) : String(v)}</Tag>
                  </p>
                ))}
              <p>
                <strong>消息：</strong> {trainResult.message}
              </p>
            </Card>
          ) : trainError ? (
            <Alert type="error" message="训练失败" description={trainError} showIcon />
          ) : (
            <Empty description="请配置超参数后点击“启动训练”" />
          )}
        </div>
      </Modal>

      {/* Predict Modal */}
      <Modal
        title={`文本预测：${selectedClassification?.name || ""}`}
        open={predictModalVisible}
        onCancel={() => {
          setPredictModalVisible(false);
          setPredictResult(null);
          setPredictText("");
        }}
        footer={[
          <Button key="close" onClick={() => setPredictModalVisible(false)}>
            关闭
          </Button>,
          <Button
            key="predict"
            type="primary"
            icon={<ThunderboltOutlined />}
            loading={submitting}
            onClick={handlePredict}
          >
            预测
          </Button>,
        ]}
      >
        <div style={{ padding: "8px 0" }}>
          <Form layout="vertical">
            <Form.Item label="输入文本" required>
              <Input.TextArea
                rows={4}
                placeholder="请输入需要预测的文本"
                value={predictText}
                onChange={(e) => setPredictText(e.target.value)}
              />
            </Form.Item>
          </Form>
          {predictResult && (
            <Card title="预测结果" size="small">
              {predictResult.error ? (
                <p style={{ color: "red" }}>
                  <strong>错误：</strong> {predictResult.error}
                </p>
              ) : (
                <>
                  <p>
                    <strong>分类ID：</strong> <Tag>{predictResult.predicted_class_id}</Tag>
                  </p>
                  <p>
                    <strong>置信度：</strong>{" "}
                    <Tag color="blue">
                      {((predictResult.confidence || 0) * 100).toFixed(2)}%
                    </Tag>
                  </p>
                </>
              )}
            </Card>
          )}
        </div>
      </Modal>

      {/* Dataset preview Modal */}
      <Modal
        title={`数据集预览：${selectedClassification?.name || ""}`}
        open={datasetModalVisible}
        width={720}
        onCancel={() => setDatasetModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDatasetModalVisible(false)}>
            关闭
          </Button>,
        ]}
      >
        {datasetLoading ? (
          <Progress percent={99} status="active" />
        ) : datasetRows.length === 0 ? (
          <Empty
            description={
              <span>
                该分类暂无训练数据，请前往{" "}
                <a href="/dashboard/training/nlp/annotation">文本数据集管理</a> 添加
              </span>
            }
          />
        ) : (
          <>
            <Alert
              type="success"
              showIcon
              style={{ marginBottom: 12 }}
              message={`共 ${datasetRows.length} 条数据${datasetRows.length > DATASET_PREVIEW_LIMIT ? `，仅预览前 ${DATASET_PREVIEW_LIMIT} 条` : ""}`}
            />
            <Table
              size="small"
              rowKey="id"
              pagination={false}
              dataSource={datasetPreview}
              columns={[
                { title: "ID", dataIndex: "id", key: "id", width: 60 },
                {
                  title: "文本",
                  dataIndex: "content",
                  ellipsis: true,
                  render: (t: string) => (
                    <span>
                      <FileTextOutlined style={{ marginRight: 6, color: "#1677ff" }} />
                      {t}
                    </span>
                  ),
                },
              ]}
            />
          </>
        )}
      </Modal>
    </div>
  );
}
