"use client";

// M35: /dashboard/tts — TTS 创作页
// 选 Model → 选 Voice → 选 Playbook → 写文本 → Generate(可选 +Subtitle)
// 音频通过 fetch+blob+createObjectURL 模式播放(M32 模式,见 MEMORY 2026-06-20)
// 历史列表用 setInterval 轮询(2s)直到 status=completed/failed

import { useEffect, useState, useCallback, useRef } from "react";
import {
  Card,
  Form,
  Select,
  Input,
  Button,
  Space,
  Table,
  Tag,
  App,
  Alert,
  Empty,
  Spin,
  Row,
  Col,
  Statistic,
  Tooltip,
} from "antd";
import {
  SoundOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
  DownloadOutlined,
  FileTextOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import {
  createTTSJob,
  listTTSJobs,
  listTTSVoices,
  buildAudioUrl,
  deleteTTSJob,
} from "@/services/tts";
import { listPlaybooks } from "@/services/playbook";
import { createSubtitle, downloadSubtitleUrl } from "@/services/subtitle";
import { modelsApi } from "@/services/models";
import type { ModelConfig } from "@/services/models";
import type { TTSJobListItem, TTSVoice } from "@/types/tts";
import type { PlaybookListItem } from "@/types/playbook";

const { TextArea } = Input;

const DEFAULT_TEXT = "你好,欢迎使用 Lumen 平台的语音合成服务。这是一个测试文本。";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("access_token");
}

interface AudioBlob {
  url: string;
  jobId: number;
}

export default function TTSPage() {
  const { message, modal } = App.useApp();
  const [form] = Form.useForm();
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [voices, setVoices] = useState<TTSVoice[]>([]);
  const [playbooks, setPlaybooks] = useState<PlaybookListItem[]>([]);
  const [modelId, setModelId] = useState<number | null>(null);
  const [voice, setVoice] = useState<string>("default");
  const [playbookId, setPlaybookId] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [history, setHistory] = useState<TTSJobListItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [audio, setAudio] = useState<AudioBlob | null>(null);
  const [fetchingAudio, setFetchingAudio] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const reloadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const res = await listTTSJobs({ page: 1, page_size: 20 });
      setHistory(res.items);
    } catch (e) {
      message.error(`加载历史失败: ${(e as Error).message}`);
    } finally {
      setHistoryLoading(false);
    }
  }, [message]);

  useEffect(() => {
    void reloadHistory();
  }, [reloadHistory]);

  // Load TTS-capable models + playbooks
  useEffect(() => {
    (async () => {
      try {
        const [m, p] = await Promise.all([
          modelsApi.list(1, 100, { is_tts: true, is_active: true }),
          listPlaybooks({ scope: "tts", page: 1, page_size: 50 }),
        ]);
        // axios response is ApiResponse<PaginatedResponse<ModelConfig>>
        const modelList = (m.data?.data ?? []) as ModelConfig[];
        setModels(modelList);
        setPlaybooks(p.items);
      } catch (e) {
        message.error(`加载配置失败: ${(e as Error).message}`);
      }
    })();
  }, [message]);

  // Load voices when model changes
  useEffect(() => {
    if (!modelId) {
      setVoices([]);
      return;
    }
    (async () => {
      try {
        const vs = await listTTSVoices(modelId);
        setVoices(vs);
        if (vs.length > 0) {
          setVoice(vs[0].id);
        }
      } catch (e) {
        message.error(`加载 voice 失败: ${(e as Error).message}`);
      }
    })();
  }, [modelId, message]);

  // Poll history every 2s while any job is non-terminal
  useEffect(() => {
    const hasRunning = history.some(
      (h) => h.status === "pending" || h.status === "running"
    );
    if (hasRunning && !pollRef.current) {
      pollRef.current = setInterval(() => void reloadHistory(), 2000);
    } else if (!hasRunning && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [history, reloadHistory]);

  const onSubmit = async (withSubtitle: boolean) => {
    const values = await form.validateFields();
    if (!modelId) {
      message.warning("请先选择 TTS 模型");
      return;
    }
    setSubmitting(true);
    try {
      const res = await createTTSJob({
        model_config_id: modelId,
        text: values.text,
        voice,
        speed: values.speed ?? 1.0,
        format: values.format ?? "mp3",
        playbook_id: playbookId,
      });
      message.success(`已提交任务 #${res.id},正在合成...`);
      void reloadHistory();
      if (withSubtitle) {
        try {
          const sub = await createSubtitle({
            script: values.text,
            // Heuristic: 1 char ≈ 0.25s (zh 4 cps). User can adjust later.
            total_duration_ms: Math.max(2000, values.text.length * 250),
            language: "zh-CN",
            tts_job_id: res.id,
          });
          message.success(`字幕已生成 #${sub.id},可下载 SRT`);
          // Trigger SRT download
          window.open(downloadSubtitleUrl(sub.id), "_blank");
        } catch (e) {
          message.error(`生成字幕失败: ${(e as Error).message}`);
        }
      }
    } catch (e) {
      message.error(`提交失败: ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const playAudio = async (jobId: number) => {
    setFetchingAudio(true);
    try {
      const token = getToken();
      if (!token) {
        message.error("未登录");
        return;
      }
      // Revoke previous object URL
      if (audio) URL.revokeObjectURL(audio.url);
      const res = await fetch(buildAudioUrl(jobId), {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      setAudio({ url, jobId });
    } catch (e) {
      message.error(`加载音频失败: ${(e as Error).message}`);
    } finally {
      setFetchingAudio(false);
    }
  };

  const downloadAudio = async (jobId: number) => {
    const token = getToken();
    if (!token) {
      message.error("未登录");
      return;
    }
    try {
      const res = await fetch(buildAudioUrl(jobId), {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `tts_${jobId}.mp3`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      message.error(`下载失败: ${(e as Error).message}`);
    }
  };

  const onDelete = async (id: number) => {
    modal.confirm({
      title: "确认删除该 TTS 任务?",
      onOk: async () => {
        try {
          await deleteTTSJob(id);
          message.success("已删除");
          void reloadHistory();
        } catch (e) {
          message.error(`删除失败: ${(e as Error).message}`);
        }
      },
    });
  };

  const columns: ColumnsType<TTSJobListItem> = [
    { title: "ID", dataIndex: "id", width: 60 },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (s: string) => {
        const color =
          s === "completed" ? "green" :
          s === "failed" ? "red" :
          s === "cancelled" ? "default" : "blue";
        return <Tag color={color}>{s}</Tag>;
      },
    },
    { title: "Voice", dataIndex: "voice", width: 180 },
    {
      title: "文本预览",
      dataIndex: "text_preview",
      ellipsis: true,
    },
    {
      title: "时长",
      dataIndex: "duration_ms",
      width: 90,
      render: (v: number | null) => (v == null ? "—" : `${(v / 1000).toFixed(1)}s`),
    },
    { title: "字符", dataIndex: "char_count", width: 70 },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 160,
      render: (v: string) => new Date(v).toLocaleString(),
    },
    {
      title: "操作",
      width: 200,
      render: (_, row) => (
        <Space>
          <Tooltip title="播放">
            <Button
              size="small"
              icon={<PlayCircleOutlined />}
              disabled={row.status !== "completed"}
              loading={fetchingAudio && audio?.jobId === row.id}
              onClick={() => void playAudio(row.id)}
            />
          </Tooltip>
          <Tooltip title="下载音频">
            <Button
              size="small"
              icon={<DownloadOutlined />}
              disabled={row.status !== "completed"}
              onClick={() => void downloadAudio(row.id)}
            />
          </Tooltip>
          <Tooltip title="删除">
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() => void onDelete(row.id)}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Row gutter={16}>
        <Col xs={24} md={14}>
          <Card
            title={
              <Space>
                <SoundOutlined />
                <span>语音合成</span>
                <Tag color="blue">M35</Tag>
              </Space>
            }
            extra={
              <Button icon={<ReloadOutlined />} onClick={() => void reloadHistory()}>
                刷新
              </Button>
            }
          >
            <Form
              form={form}
              layout="vertical"
              initialValues={{
                text: DEFAULT_TEXT,
                speed: 1.0,
                format: "mp3",
              }}
            >
              <Form.Item label="TTS 模型" required>
                <Select
                  placeholder="选择 TTS 模型"
                  value={modelId ?? undefined}
                  onChange={setModelId}
                  options={models.map((m) => ({
                    label: `${m.name} (${m.model_type})`,
                    value: m.id,
                  }))}
                  virtual={false}
                />
              </Form.Item>
              <Form.Item label="Voice">
                <Select
                  value={voice}
                  onChange={setVoice}
                  options={voices.map((v) => ({
                    label: `${v.name} (${v.language}, ${v.gender})`,
                    value: v.id,
                  }))}
                  placeholder={voices.length === 0 ? "请先选模型" : "选择 voice"}
                  disabled={voices.length === 0}
                  virtual={false}
                />
              </Form.Item>
              <Form.Item label="Playbook(可选)">
                <Select
                  value={playbookId}
                  onChange={setPlaybookId}
                  allowClear
                  placeholder="无 / 选择风格"
                  options={playbooks.map((p) => ({
                    label: `${p.name}${p.is_builtin ? " (内置)" : ""}`,
                    value: p.id,
                  }))}
                  virtual={false}
                />
              </Form.Item>
              <Row gutter={12}>
                <Col span={12}>
                  <Form.Item name="speed" label="速度">
                    <Select
                      options={[
                        { label: "0.5x", value: 0.5 },
                        { label: "0.75x", value: 0.75 },
                        { label: "1.0x", value: 1.0 },
                        { label: "1.25x", value: 1.25 },
                        { label: "1.5x", value: 1.5 },
                        { label: "2.0x", value: 2.0 },
                      ]}
                    />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="format" label="格式">
                    <Select
                      options={[
                        { label: "MP3", value: "mp3" },
                        { label: "WAV", value: "wav" },
                        { label: "Opus", value: "opus" },
                        { label: "FLAC", value: "flac" },
                      ]}
                    />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item
                name="text"
                label="文本"
                rules={[{ required: true, min: 1, max: 10000 }]}
              >
                <TextArea
                  rows={6}
                  showCount
                  maxLength={10000}
                  placeholder="输入要合成的文本..."
                />
              </Form.Item>
              <Form.Item>
                <Space>
                  <Button
                    type="primary"
                    icon={<SoundOutlined />}
                    onClick={() => void onSubmit(false)}
                    loading={submitting}
                  >
                    Generate
                  </Button>
                  <Button
                    icon={<FileTextOutlined />}
                    onClick={() => void onSubmit(true)}
                    loading={submitting}
                  >
                    Generate + Subtitle
                  </Button>
                </Space>
              </Form.Item>
            </Form>
          </Card>

          {audio && (
            <Card style={{ marginTop: 16 }} title="最近播放">
              <Space direction="vertical" style={{ width: "100%" }}>
                <Alert
                  message={`任务 #${audio.jobId} 的音频已加载(blob + createObjectURL 模式)`}
                  type="success"
                  showIcon
                />
                {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
                <audio
                  controls
                  src={audio.url}
                  style={{ width: "100%" }}
                />
              </Space>
            </Card>
          )}
        </Col>

        <Col xs={24} md={10}>
          <Card title="历史任务">
            <Spin spinning={historyLoading}>
              {history.length === 0 ? (
                <Empty description="暂无任务" />
              ) : (
                <Table
                  rowKey="id"
                  size="small"
                  columns={columns}
                  dataSource={history}
                  pagination={false}
                />
              )}
            </Spin>
          </Card>
          <Card style={{ marginTop: 16 }} title="统计">
            <Space size="large" wrap>
              <Statistic
                title="总计"
                value={history.length}
                prefix={<SoundOutlined />}
              />
              <Statistic
                title="已完成"
                value={history.filter((h) => h.status === "completed").length}
                valueStyle={{ color: "#52c41a" }}
              />
              <Statistic
                title="进行中"
                value={history.filter((h) => h.status === "pending" || h.status === "running").length}
                valueStyle={{ color: "#1890ff" }}
              />
            </Space>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
