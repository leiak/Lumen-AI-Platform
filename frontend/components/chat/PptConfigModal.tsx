"use client";

import { useState, useRef } from "react";
import {
  Modal,
  Form,
  Input,
  Select,
  Checkbox,
  Radio,
  Button,
  App,
  Alert,
  Space,
  Progress,
  Tooltip,
} from "antd";
import { FilePptOutlined, DownloadOutlined, CheckCircleOutlined } from "@ant-design/icons";
import type { PptConfig } from "@/types/ppt";
import { pptApi } from "@/services/ppt";

interface PptConfigModalProps {
  open: boolean;
  conversationId: number;
  conversationTitle?: string;
  onClose: () => void;
}

type PptStatus = "idle" | "generating" | "polling" | "completed" | "failed";

const CONTENT_RANGE_OPTIONS = [
  { value: 1, label: "最后 1 条消息" },
  { value: 5, label: "最近 5 条消息" },
  { value: 10, label: "最近 10 条消息" },
  { value: 20, label: "最近 20 条消息" },
  { value: 0, label: "全部消息" },
];

const STYLE_OPTIONS = [
  { value: "simple", label: "简约", desc: "克制留白，灰阶图表" },
  { value: "business", label: "商务", desc: "深蓝主色，KPI 图表" },
  { value: "academic", label: "学术", desc: "衬线字体，学术配色" },
];

export function PptConfigModal({
  open,
  conversationId,
  conversationTitle,
  onClose,
}: PptConfigModalProps) {
  const { message } = App.useApp();
  const [form] = Form.useForm<PptConfig>();
  const [status, setStatus] = useState<PptStatus>("idle");
  const [progress, setProgress] = useState(0);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const pollingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:11335";

  const reset = () => {
    setStatus("idle");
    setProgress(0);
    setDownloadUrl(null);
    setErrorMsg(null);
    if (pollingTimerRef.current) {
      clearTimeout(pollingTimerRef.current);
      pollingTimerRef.current = null;
    }
  };

  const handleClose = () => {
    reset();
    form.resetFields();
    onClose();
  };

  const startPolling = (taskId: string, filename: string, token: string) => {
    const maxAttempts = 60;
    let attempts = 0;

    const poll = () => {
      attempts++;
      setProgress(Math.min(Math.round((attempts / maxAttempts) * 100), 95));

      pptApi
        .getTask(taskId)
        .then((res) => {
          if (res.data.code !== 200 || !res.data.data) {
            if (attempts < maxAttempts) {
              pollingTimerRef.current = setTimeout(poll, 3000);
            } else {
              setStatus("failed");
              setErrorMsg("PPT 生成超时");
            }
            return;
          }

          const task = res.data.data;
          if (task.status === "completed") {
            setProgress(100);
            setDownloadUrl(pptApi.getDownloadUrl(taskId, baseUrl));
            setStatus("completed");
            message.success("PPT 生成完毕！点击下方按钮下载");
          } else if (task.status === "failed") {
            setStatus("failed");
            setErrorMsg(task.error || "生成失败");
          } else {
            // pending / processing，继续轮询
            if (attempts < maxAttempts) {
              pollingTimerRef.current = setTimeout(poll, 3000);
            } else {
              setStatus("failed");
              setErrorMsg("PPT 生成超时");
            }
          }
        })
        .catch(() => {
          if (attempts < maxAttempts) {
            pollingTimerRef.current = setTimeout(poll, 3000);
          } else {
            setStatus("failed");
            setErrorMsg("网络错误，请稍后重试");
          }
        });
    };

    pollingTimerRef.current = setTimeout(poll, 2000);
  };

  const handleGenerate = async () => {
    try {
      const values = await form.validateFields();
      setStatus("generating");
      setErrorMsg(null);
      setDownloadUrl(null);

      const config: PptConfig = {
        title: values.title,
        contentRange: values.contentRange,
        includeCharts: values.includeCharts,
        style: values.style,
        mode: values.mode,
      };

      const token = localStorage.getItem("access_token") || "";
      const filename = config.title || conversationTitle || "PPT 演示文稿";

      if (config.mode === "frontend") {
        // 前端实时模式：调 Next.js API route 做服务端渲染
        const res = await pptApi.generate(config, conversationId);
        if (res.data.code !== 200 || !res.data.data?.schema) {
          message.error(res.data.message || "PPT 生成失败");
          setStatus("idle");
          return;
        }

        // 调 Next.js API route（服务端渲染 pptxgenjs，返回 base64）
        const renderRes = await fetch("/api/v1/ppt/render", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            schema: res.data.data.schema,
            style: config.style,
            filename,
          }),
        });
        if (!renderRes.ok) {
          message.error("PPT 渲染失败");
          setStatus("idle");
          return;
        }
        const renderJson = await renderRes.json();
        if (!renderJson.data) {
          message.error("PPT 渲染失败: " + (renderJson.error || "未知错误"));
          setStatus("idle");
          return;
        }
        // base64 → Uint8Array → Blob
        const binaryString = atob(renderJson.data);
        const bytes = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
          bytes[i] = binaryString.charCodeAt(i);
        }
        const blob = new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.presentationml.presentation" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${filename}.pptx`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        message.success("PPT 已生成并下载");
        handleClose();
      } else {
        // 后端高精度模式
        const res = await pptApi.generate(config, conversationId);
        if (res.data.code !== 200 || !res.data.data?.task_id) {
          message.error(res.data.message || "PPT 生成失败");
          setStatus("idle");
          return;
        }

        setStatus("polling");
        startPolling(res.data.data.task_id, filename, token);
      }
    } catch (err: any) {
      if (err.errorFields) return;
      message.error(`PPT 生成失败: ${err?.message || err}`);
      setStatus("idle");
    }
  };

  const handleDownload = async () => {
    if (!downloadUrl) return;
    const token = localStorage.getItem("access_token") || "";
    try {
      const fileRes = await fetch(downloadUrl, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!fileRes.ok) throw new Error("download failed");
      const blob = await fileRes.blob();
      const fn = conversationTitle || "PPT 演示文稿";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${fn}.pptx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      message.error("下载失败，请重试");
    }
  };

  const footerContent = () => {
    if (status === "idle" || status === "generating") {
      return [
        <Button key="cancel" onClick={handleClose} disabled={status === "generating"}>
          取消
        </Button>,
        <Button
          key="generate"
          type="primary"
          loading={status === "generating"}
          onClick={handleGenerate}
        >
          {status === "generating" ? "正在提交..." : "开始生成"}
        </Button>,
      ];
    }

    if (status === "polling") {
      return [
        <Button key="cancel" onClick={handleClose}>
          关闭
        </Button>,
      ];
    }

    if (status === "completed") {
      return [
        <Button key="cancel" onClick={handleClose}>
          关闭
        </Button>,
        <Button
          key="download"
          type="primary"
          icon={<DownloadOutlined />}
          onClick={handleDownload}
        >
          下载 PPT
        </Button>,
      ];
    }

    if (status === "failed") {
      return [
        <Button key="cancel" onClick={handleClose}>
          关闭
        </Button>,
        <Button key="retry" type="primary" onClick={reset}>
          重试
        </Button>,
      ];
    }
  };

  return (
    <Modal
      title={
        <Space>
          <FilePptOutlined />
          生成 PPT
        </Space>
      }
      open={open}
      onCancel={handleClose}
      footer={footerContent()}
      width={480}
      maskClosable={status === "idle" || status === "failed"}
      closable={status === "idle" || status === "failed"}
    >
      {status === "idle" && (
        <>
          <Form
            form={form}
            layout="vertical"
            initialValues={{
              contentRange: 10,
              includeCharts: false,
              style: "simple",
              mode: "backend",
            }}
          >
            <Form.Item name="title" label="PPT 标题">
              <Input placeholder="留空则由 AI 根据对话内容自动生成" />
            </Form.Item>

            <Form.Item name="contentRange" label="内容范围" rules={[{ required: true }]}>
              <Select options={CONTENT_RANGE_OPTIONS} />
            </Form.Item>

            <Form.Item name="includeCharts" valuePropName="checked">
              <Checkbox>包含图表（AI 判断何时插入）</Checkbox>
            </Form.Item>

            <Form.Item name="style" label="模板风格" rules={[{ required: true }]}>
              <Radio.Group optionType="button" buttonStyle="solid">
                {STYLE_OPTIONS.map((o) => (
                  <Tooltip key={o.value} title={o.desc}>
                    <Radio.Button value={o.value}>{o.label}</Radio.Button>
                  </Tooltip>
                ))}
              </Radio.Group>
            </Form.Item>

            <Form.Item name="mode" label="生成方式" rules={[{ required: true }]}>
              <Radio.Group>
                <Space direction="vertical">
                  <Radio value="backend">
                    <strong>后端高精度</strong>（python-pptx 渲染）
                  </Radio>
                  <Radio value="frontend">
                    <strong>前端实时</strong>（pptxgenjs 渲染，速度快）
                  </Radio>
                </Space>
              </Radio.Group>
            </Form.Item>
          </Form>

          <Alert
            type="info"
            showIcon
            message="AI 会根据所选内容范围和对话主题生成 PPT 大纲。"
            style={{ marginTop: 8 }}
          />
        </>
      )}

      {status === "generating" && (
        <Space direction="vertical" style={{ width: "100%", padding: "20px 0" }}>
          <div style={{ textAlign: "center", color: "#666" }}>正在提交生成任务...</div>
        </Space>
      )}

      {status === "polling" && (
        <Space direction="vertical" style={{ width: "100%", padding: "20px 0" }}>
          <CheckCircleOutlined style={{ fontSize: 40, color: "#1890ff", display: "block", textAlign: "center" }} />
          <div style={{ textAlign: "center", color: "#666", marginTop: 12 }}>
            PPT 正在生成中，请稍候...
          </div>
          <Progress
            percent={progress}
            status="active"
            strokeColor="#1890ff"
            style={{ marginTop: 16 }}
          />
          <div style={{ textAlign: "center", color: "#aaa", fontSize: 12 }}>
            通常需要 10~30 秒，请勿关闭此窗口
          </div>
        </Space>
      )}

      {status === "completed" && (
        <Space direction="vertical" style={{ width: "100%", padding: "20px 0" }}>
          <CheckCircleOutlined style={{ fontSize: 48, color: "#52c41a", display: "block", textAlign: "center" }} />
          <div style={{ textAlign: "center", fontSize: 16, fontWeight: 600, marginTop: 12 }}>
            PPT 生成完毕！
          </div>
          <div style={{ textAlign: "center", color: "#666", marginTop: 4 }}>
            点击下方按钮下载 .pptx 文件
          </div>
        </Space>
      )}

      {status === "failed" && (
        <Space direction="vertical" style={{ width: "100%", padding: "20px 0" }}>
          <div style={{ textAlign: "center", color: "#ff4d4f", fontSize: 16 }}>
            生成失败
          </div>
          <div style={{ textAlign: "center", color: "#888", marginTop: 4 }}>
            {errorMsg || "未知错误"}
          </div>
        </Space>
      )}
    </Modal>
  );
}
