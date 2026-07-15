"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import {
  Tabs,
  Table,
  Button,
  Modal,
  Form,
  Input,
  message,
  Popconfirm,
  Card,
  Space,
  Tag,
  Progress,
  InputNumber,
  Switch,
  Select,
  Divider,
  Tooltip,
  Empty,
  Statistic,
  Row,
  Col,
  Upload,
} from "antd";
import {
  PlusOutlined,
  PlayCircleOutlined,
  UploadOutlined,
  PictureOutlined,
  DeleteOutlined,
  ReloadOutlined,
  ExperimentOutlined,
  CheckCircleTwoTone,
  CloseCircleTwoTone,
} from "@ant-design/icons";
import type { UploadProps } from "antd";
import {
  visionApi,
  VisionClassification,
  VisionImage,
  TrainResult,
  PendingImage,
  VisionTrainingConfig,
  VisionArchitecture,
  VISION_ARCHITECTURE_LABELS,
  DEFAULT_TRAINING_CONFIG,
  createImagePreviewUrl,
  revokeImagePreviewUrl,
} from "@/services/vision";

const { TabPane } = Tabs;

/* ------------------------------------------------------------------ */
/*  Datasets tab                                                      */
/* ------------------------------------------------------------------ */

function DatasetsTab(props: {
  classifications: VisionClassification[];
  total: number;
  loading: boolean;
  onRefresh: () => Promise<void>;
  onSelectForTraining: (c: VisionClassification) => void;
}) {
  const { classifications, total, loading, onRefresh, onSelectForTraining } = props;
  const [modalVisible, setModalVisible] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const handleCreate = async (values: any) => {
    setSubmitting(true);
    try {
      const response = await visionApi.createClassification(values);
      if (response.data?.code === 200) {
        message.success("创建成功");
        setModalVisible(false);
        form.resetFields();
        await onRefresh();
      } else {
        message.error(response.data?.message || "创建失败");
      }
    } catch (error: any) {
      message.error(error?.response?.data?.message || "创建失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    setDeletingId(id);
    try {
      const response = await visionApi.deleteClassification(id);
      if (response.data?.code === 200) {
        message.success("删除成功");
        await onRefresh();
      } else {
        message.error(response.data?.message || "删除失败");
      }
    } catch (error: any) {
      message.error(error?.response?.data?.message || "删除失败");
    } finally {
      setDeletingId(null);
    }
  };

  const columns = [
    { title: "ID", dataIndex: "id", key: "id", width: 60 },
    { title: "名称", dataIndex: "name", key: "name" },
    { title: "描述", dataIndex: "description", key: "description", ellipsis: true },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 180,
      render: (v: string) => (v ? new Date(v).toLocaleString() : "-"),
    },
    {
      title: "操作",
      key: "action",
      width: 220,
      render: (_: any, record: VisionClassification) => (
        <Space>
          <Tooltip title="切换到训练面板并预选此分类">
            <Button
              size="small"
              type="primary"
              icon={<ExperimentOutlined />}
              onClick={() => onSelectForTraining(record)}
            >
              训练
            </Button>
          </Tooltip>
          <Popconfirm title="确认删除该分类及其图片?" onConfirm={() => handleDelete(record.id)}>
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              loading={deletingId === record.id}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title="图像分类（数据集）"
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={onRefresh} loading={loading}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalVisible(true)}>
            创建分类
          </Button>
        </Space>
      }
    >
      <Table
        columns={columns}
        dataSource={classifications}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 10, total, showTotal: (t) => `共 ${t} 条` }}
        locale={{ emptyText: <Empty description="暂无数据集" /> }}
      />

      <Modal
        title="创建分类"
        open={modalVisible}
        onCancel={() => {
          setModalVisible(false);
          form.resetFields();
        }}
        footer={null}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input placeholder="请输入分类名称（如 cats）" maxLength={100} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="描述该数据集的用途" maxLength={500} />
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
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Image gallery (used inside TrainTab)                              */
/* ------------------------------------------------------------------ */

function ImageGallery(props: {
  classification: VisionClassification;
  images: VisionImage[];
  onRefresh: () => Promise<void>;
}) {
  const { classification, images, onRefresh } = props;
  const [pending, setPending] = useState<PendingImage[]>([]);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  // Clean up object URLs on unmount or when pending set changes.
  useEffect(() => {
    return () => {
      pending.forEach((p) => revokeImagePreviewUrl(p.previewUrl));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFiles = (files: File[]) => {
    const next: PendingImage[] = files.map((file) => ({
      uid: `${Date.now()}-${file.name}-${Math.random().toString(36).slice(2, 7)}`,
      file,
      previewUrl: createImagePreviewUrl(file),
    }));
    setPending((prev) => [...prev, ...next]);
  };

  const removePending = (uid: string) => {
    setPending((prev) => {
      const target = prev.find((p) => p.uid === uid);
      if (target) revokeImagePreviewUrl(target.previewUrl);
      return prev.filter((p) => p.uid !== uid);
    });
  };

  const uploadAll = async () => {
    if (pending.length === 0) {
      message.warning("请先选择图片");
      return;
    }
    setUploading(true);
    let successCount = 0;
    let failCount = 0;
    for (const item of pending) {
      try {
        const res = await visionApi.uploadImage(classification.id, item.file);
        if (res.data?.code === 200) {
          successCount += 1;
        } else {
          failCount += 1;
        }
      } catch {
        failCount += 1;
      }
    }
    // Free preview URLs
    pending.forEach((p) => revokeImagePreviewUrl(p.previewUrl));
    setPending([]);
    setUploading(false);
    if (successCount > 0) {
      message.success(`上传成功 ${successCount} 张${failCount > 0 ? `, 失败 ${failCount} 张` : ""}`);
      await onRefresh();
    } else {
      message.error("上传失败");
    }
  };

  const handleDelete = async (id: number) => {
    setDeletingId(id);
    try {
      const res = await visionApi.deleteImage(id);
      if (res.data?.code === 200) {
        message.success("删除成功");
        await onRefresh();
      } else {
        message.error(res.data?.message || "删除失败");
      }
    } catch {
      message.error("删除失败");
    } finally {
      setDeletingId(null);
    }
  };

  const uploadProps: UploadProps = {
    accept: "image/*",
    multiple: true,
    showUploadList: false,
    beforeUpload: (file, fileList) => {
      // Defer until user clicks "确认上传" — keep all files in `pending`.
      handleFiles(fileList.length > 0 && file === fileList[0] ? fileList : [file]);
      return false;
    },
  };

  return (
    <Card
      size="small"
      title={
        <Space>
          <PictureOutlined />
          <span>数据预览 — {classification.name}</span>
          <Tag color="blue">{images.length} 张已上传</Tag>
          {pending.length > 0 && <Tag color="orange">{pending.length} 张待上传</Tag>}
        </Space>
      }
      extra={
        <Space>
          <Upload {...uploadProps}>
            <Button icon={<UploadOutlined />}>选择图片</Button>
          </Upload>
          <Button
            type="primary"
            onClick={uploadAll}
            disabled={pending.length === 0}
            loading={uploading}
          >
            确认上传 ({pending.length})
          </Button>
        </Space>
      }
    >
      {images.length === 0 && pending.length === 0 ? (
        <Empty description="暂无图片，请先上传（每个分类至少 2 张）" />
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
            gap: 12,
          }}
        >
          {images.map((img) => (
            <div
              key={`s-${img.id}`}
              style={{
                position: "relative",
                border: "1px solid #f0f0f0",
                borderRadius: 6,
                padding: 6,
                background: "#fafafa",
              }}
            >
              <div
                style={{
                  width: "100%",
                  aspectRatio: "1 / 1",
                  background: "#fff",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  borderRadius: 4,
                  overflow: "hidden",
                }}
              >
                <PictureOutlined style={{ fontSize: 32, color: "#bfbfbf" }} />
              </div>
              <div
                title={img.filename}
                style={{
                  fontSize: 12,
                  marginTop: 6,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {img.filename}
              </div>
              <div style={{ fontSize: 11, color: "#999" }}>ID: {img.id}</div>
              <Button
                size="small"
                type="text"
                danger
                icon={<DeleteOutlined />}
                loading={deletingId === img.id}
                onClick={() => handleDelete(img.id)}
                style={{ position: "absolute", top: 4, right: 4 }}
              />
            </div>
          ))}
          {pending.map((p) => (
            <div
              key={p.uid}
              style={{
                position: "relative",
                border: "1px dashed #faad14",
                borderRadius: 6,
                padding: 6,
                background: "#fffbe6",
              }}
            >
              <div
                style={{
                  width: "100%",
                  aspectRatio: "1 / 1",
                  background: `center / cover no-repeat url(${p.previewUrl})`,
                  borderRadius: 4,
                  overflow: "hidden",
                }}
              />
              <div
                title={p.file.name}
                style={{
                  fontSize: 12,
                  marginTop: 6,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {p.file.name}
              </div>
              <div style={{ fontSize: 11, color: "#d48806" }}>{(p.file.size / 1024).toFixed(1)} KB</div>
              <Button
                size="small"
                type="text"
                danger
                icon={<DeleteOutlined />}
                onClick={() => removePending(p.uid)}
                style={{ position: "absolute", top: 4, right: 4 }}
              />
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Training config + results                                         */
/* ------------------------------------------------------------------ */

function TrainingPanel(props: {
  selected: VisionClassification | null;
  images: VisionImage[];
  onRefreshImages: () => Promise<void>;
  onNeedClassification: () => void;
}) {
  const { selected, images, onRefreshImages, onNeedClassification } = props;
  const [configForm] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<TrainResult | null>(null);

  if (!selected) {
    return (
      <Card>
        <Empty description="请先在“数据集”标签中选择要训练的分类，然后点击该行的“训练”按钮" />
      </Card>
    );
  }

  const trainSample = Math.max(0, Math.floor(images.length * (1 - 0.2)));
  const testSample = Math.max(0, images.length - trainSample);

  const handleTrain = async () => {
    if (images.length < 2) {
      message.warning("至少需要 2 张图片才能进行训练");
      return;
    }
    let values: Omit<VisionTrainingConfig, "classification_id">;
    try {
      values = await configForm.validateFields();
    } catch {
      return; // antd already surfaces the error
    }
    setSubmitting(true);
    setResult(null);
    try {
      const res = await visionApi.train({ classification_id: selected.id, ...values });
      const body = res.data;
      if (body?.code === 200) {
        setResult(body.data as TrainResult);
        message.success("训练完成");
      } else {
        message.error(body?.message || "训练失败");
        setResult({
          status: "error",
          message: body?.message || "训练失败",
        });
      }
    } catch (error: any) {
      const msg = error?.response?.data?.message || error?.message || "训练失败";
      message.error(msg);
      setResult({ status: "error", message: msg });
    } finally {
      setSubmitting(false);
    }
  };

  // Build a synthetic per-epoch accuracy curve for the CSS bar chart.
  // The backend only returns a single final accuracy value, so we
  // project a plausible ascending curve and mark the final point.
  const accuracyCurve = useMemo(() => {
    if (!result || typeof result.accuracy !== "number") return [];
    const final = result.accuracy;
    const epochs = Math.max(1, Number(configForm.getFieldValue("epochs")) || 10);
    // Lightly-decreasing noise from a high start to the final value.
    return Array.from({ length: epochs }, (_, i) => {
      const t = (i + 1) / epochs;
      // Start at 0.5 (random baseline) and ease toward `final`.
      const eased = 0.5 + (final - 0.5) * t;
      return Math.max(0, Math.min(1, eased));
    });
  }, [result, configForm]);

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <ImageGallery
        classification={selected}
        images={images}
        onRefresh={onRefreshImages}
      />

      <Card
        size="small"
        title={
          <Space>
            <ExperimentOutlined />
            <span>训练配置 — {selected.name}</span>
          </Space>
        }
        extra={
          <Button onClick={onNeedClassification}>重新选择分类</Button>
        }
      >
        <Form
          form={configForm}
          layout="vertical"
          initialValues={DEFAULT_TRAINING_CONFIG}
          disabled={submitting}
        >
          <Row gutter={16}>
            <Col xs={24} sm={12} md={8}>
              <Form.Item label="模型架构" name="architecture" tooltip="后端当前固定使用 Logistic Regression；此字段为前向兼容">
                <Select<VisionArchitecture>
                  options={(Object.keys(VISION_ARCHITECTURE_LABELS) as VisionArchitecture[]).map(
                    (k) => ({ value: k, label: VISION_ARCHITECTURE_LABELS[k] }),
                  )}
                />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8}>
              <Form.Item label="训练轮数 (epochs)" name="epochs" rules={[{ required: true }]}>
                <InputNumber min={1} max={500} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8}>
              <Form.Item label="批大小 (batch size)" name="batch_size" rules={[{ required: true }]}>
                <InputNumber min={1} max={512} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8}>
              <Form.Item label="图像尺寸 (px)" name="image_size" tooltip="特征提取会将图片缩放到该尺寸">
                <Select
                  options={[32, 64, 96, 128, 160, 224, 256, 320, 384].map((n) => ({
                    value: n,
                    label: `${n} × ${n}`,
                  }))}
                />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8}>
              <Form.Item label="学习率" name="learning_rate">
                <InputNumber
                  min={0.00001}
                  max={1}
                  step={0.0001}
                  style={{ width: "100%" }}
                  formatter={(v) => (v == null ? "" : String(v))}
                />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8}>
              <Form.Item
                label="训练 / 测试集切分"
                name="train_test_split"
                tooltip="测试集占比（0~1）。后端默认 0.2"
              >
                <InputNumber min={0.05} max={0.5} step={0.05} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8}>
              <Form.Item label="数据增强" name="augment" valuePropName="checked">
                <Switch checkedChildren="开启" unCheckedChildren="关闭" />
              </Form.Item>
            </Col>
          </Row>

          <Divider style={{ margin: "12px 0" }} />

          <Space wrap>
            <Tag color="blue">分类 ID: {selected.id}</Tag>
            <Tag>已上传图片: {images.length}</Tag>
            <Tag color="cyan">预估训练集: {trainSample}</Tag>
            <Tag color="purple">预估测试集: {testSample}</Tag>
            <Tooltip title="后端同步训练，无需轮询">
              <Tag color="default">同步模式</Tag>
            </Tooltip>
          </Space>

          <Divider style={{ margin: "12px 0" }} />

          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={submitting}
            onClick={handleTrain}
            size="large"
            disabled={images.length < 2}
          >
            开始训练
          </Button>
          {images.length < 2 && (
            <span style={{ marginLeft: 12, color: "#fa8c16" }}>
              至少需要 2 张图片才能训练
            </span>
          )}
        </Form>
      </Card>

      {submitting && (
        <Card>
          <div style={{ textAlign: "center", padding: "20px 0" }}>
            <Progress type="circle" percent={99} status="active" size={120} />
            <p style={{ marginTop: 16 }}>正在训练模型，请稍候…</p>
          </div>
        </Card>
      )}

      {result && !submitting && (
        <Card
          size="small"
          title={
            <Space>
              {result.status === "success" ? (
                <CheckCircleTwoTone twoToneColor="#52c41a" />
              ) : (
                <CloseCircleTwoTone twoToneColor="#ff4d4f" />
              )}
              <span>训练结果</span>
            </Space>
          }
        >
          <Row gutter={16}>
            <Col xs={24} sm={12} md={6}>
              <Statistic
                title="状态"
                value={result.status === "success" ? "成功" : "失败"}
                valueStyle={{
                  color: result.status === "success" ? "#52c41a" : "#ff4d4f",
                }}
              />
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Statistic
                title="准确率 (Accuracy)"
                value={
                  typeof result.accuracy === "number"
                    ? (result.accuracy * 100).toFixed(2)
                    : "—"
                }
                suffix="%"
                valueStyle={{ color: "#1890ff" }}
              />
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Statistic title="训练样本 (预估)" value={trainSample} />
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Statistic title="测试样本 (预估)" value={testSample} />
            </Col>
          </Row>

          {typeof result.accuracy === "number" && accuracyCurve.length > 0 && (
            <>
              <Divider style={{ margin: "16px 0" }} />
              <div style={{ fontSize: 13, color: "#666", marginBottom: 8 }}>
                训练过程准确率（推演曲线，末点为实际值）
              </div>
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-end",
                  gap: 2,
                  height: 120,
                  padding: "8px 4px",
                  border: "1px solid #f0f0f0",
                  borderRadius: 4,
                  background: "#fafafa",
                }}
              >
                {accuracyCurve.map((v, i) => {
                  const isLast = i === accuracyCurve.length - 1;
                  return (
                    <Tooltip key={i} title={`Epoch ${i + 1}: ${(v * 100).toFixed(1)}%`}>
                      <div
                        style={{
                          flex: 1,
                          minWidth: 4,
                          height: `${Math.max(2, v * 100)}%`,
                          background: isLast ? "#52c41a" : "#91caff",
                          borderRadius: 2,
                          transition: "height 0.3s",
                        }}
                      />
                    </Tooltip>
                  );
                })}
              </div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: 11,
                  color: "#999",
                  marginTop: 4,
                  padding: "0 4px",
                }}
              >
                <span>Epoch 1</span>
                <span>Epoch {accuracyCurve.length}</span>
              </div>
            </>
          )}

          <Divider style={{ margin: "16px 0" }} />
          <div>
            <strong>消息：</strong>
            <span style={{ marginLeft: 8 }}>{result.message}</span>
          </div>
          {result.model_path && (
            <div style={{ marginTop: 8 }}>
              <strong>模型路径：</strong>
              <code style={{ marginLeft: 8, fontSize: 12 }}>{result.model_path}</code>
            </div>
          )}
        </Card>
      )}
    </Space>
  );
}

/* ------------------------------------------------------------------ */
/*  Page root                                                         */
/* ------------------------------------------------------------------ */

export default function VisionClassificationPage() {
  const [classifications, setClassifications] = useState<VisionClassification[]>([]);
  const [classificationsTotal, setClassificationsTotal] = useState(0);
  const [listLoading, setListLoading] = useState(false);
  const [images, setImages] = useState<VisionImage[]>([]);
  const [selected, setSelected] = useState<VisionClassification | null>(null);
  const [activeTab, setActiveTab] = useState<string>("datasets");

  const fetchClassifications = useCallback(async () => {
    setListLoading(true);
    try {
      const res = await visionApi.listClassifications(1, 100);
      if (res.data?.code === 200) {
        setClassifications(res.data.data || []);
        // Surface the real server total even though the local Table only
        // shows one page worth of data.
        setClassificationsTotal(res.data.total || (res.data.data || []).length);
      } else {
        message.error(res.data?.message || "获取分类列表失败");
      }
    } catch (error: any) {
      message.error(error?.response?.data?.message || "获取分类列表失败");
    } finally {
      setListLoading(false);
    }
  }, []);

  const fetchImages = useCallback(async (classificationId: number) => {
    try {
      const res = await visionApi.listImages(classificationId, 1, 200);
      if (res.data?.code === 200) {
        setImages(res.data.data || []);
      } else {
        message.error(res.data?.message || "获取图像列表失败");
      }
    } catch (error: any) {
      message.error(error?.response?.data?.message || "获取图像列表失败");
    }
  }, []);

  useEffect(() => {
    fetchClassifications();
  }, [fetchClassifications]);

  useEffect(() => {
    if (selected) {
      fetchImages(selected.id);
    } else {
      setImages([]);
    }
  }, [selected, fetchImages]);

  const handleSelectForTraining = (c: VisionClassification) => {
    setSelected(c);
    setActiveTab("train");
  };

  return (
    <div style={{ padding: 24 }}>
      <Tabs activeKey={activeTab} onChange={setActiveTab}>
        <TabPane tab="数据集" key="datasets">
          <DatasetsTab
            classifications={classifications}
            total={classificationsTotal}
            loading={listLoading}
            onRefresh={fetchClassifications}
            onSelectForTraining={handleSelectForTraining}
          />
        </TabPane>
        <TabPane
          tab={
            <Space>
              <ExperimentOutlined />
              <span>训练</span>
              {selected && <Tag color="processing">{selected.name}</Tag>}
            </Space>
          }
          key="train"
        >
          <TrainingPanel
            selected={selected}
            images={images}
            onRefreshImages={() => (selected ? fetchImages(selected.id) : Promise.resolve())}
            onNeedClassification={() => setActiveTab("datasets")}
          />
        </TabPane>
      </Tabs>
    </div>
  );
}
