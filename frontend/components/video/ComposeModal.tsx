"use client";

// frontend/components/video/ComposeModal.tsx
// M36.1 — submit a new VideoComposeCreate payload.
//
// Form layout:
//   - source_images (Form.List, ≥1 项) — 每行有缩略图 + 文本输入 +
//     "从我的图片库选" 按钮(打开二级 ImagePickerModal)
//   - audio_path (paste-Input,可粘贴 generated_audios.id 或本地路径)
//   - subtitle_path (paste-Input,同上)
//   - playbook_id (PlaybookSelect,scope=video)
//   - 高级:resolution / fps / audio_fade_in/out / per_image_seconds
//
// 提交后 backend 异步 FFmpeg 合成,前端轮询(`/dashboard/videos` page 5s refetch)。

import { useEffect, useState } from "react";
import {
  Modal,
  Form,
  Input,
  Select,
  InputNumber,
  Radio,
  Button,
  App,
  Tag,
  Space,
} from "antd";
import { PlusOutlined, DeleteOutlined, AppstoreAddOutlined, AudioOutlined, FileTextOutlined, PictureOutlined, CustomerServiceOutlined } from "@ant-design/icons";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createVideoCompose } from "@/services/video";
import { imageGenerationApi } from "@/services/image-generation";
import { buildStockImageUrl } from "@/services/stock";
import PlaybookSelect from "@/components/PlaybookSelect";
import { ImagePickerModal } from "./ImagePickerModal";
import { StockPickerModal } from "./StockPickerModal";
import { AudioPickerModal } from "./AudioPickerModal";
import { SubtitlePickerModal } from "./SubtitlePickerModal";
import { MusicPickerModal } from "./MusicPickerModal";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:11335/api/v1";

export interface ComposeModalProps {
  open: boolean;
  onClose: () => void;
}

interface SourceImagePreviewProps {
  src: string;
}

// 解析 source string → image id(若是 URL 形态)。
function parseImageId(src: string): number | undefined {
  const m = src.match(/\/api\/v1\/image-generation\/(\d+)\/image/);
  return m ? Number(m[1]) : undefined;
}

// 解析 source string → 本地路径态的缩略图(若是 /image-generation/{id}/image
// 形态,前端显示后端 thumbnail 端点;其他形态显示一个 placeholder)。
function SourceImagePreview({ src }: { src: string }) {
  const id = parseImageId(src);
  if (id !== undefined) {
    return (
      <img
        src={`${API_BASE}${imageGenerationApi.thumbnailPath(id)}`}
        alt={`image-${id}`}
        style={{
          width: 80,
          height: 80,
          objectFit: "cover",
          borderRadius: 4,
          marginRight: 8,
        }}
      />
    );
  }
  return (
    <div
      style={{
        width: 80,
        height: 80,
        borderRadius: 4,
        background: "#f0f0f0",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "#999",
        fontSize: 12,
        marginRight: 8,
      }}
    >
      {src.length > 20 ? `${src.slice(0, 20)}…` : src || "空"}
    </div>
  );
}

export function ComposeModal({ open, onClose }: ComposeModalProps) {
  const [form] = Form.useForm();
  const { message } = App.useApp();
  const qc = useQueryClient();

  // Form.List 的 source_images 数组(每项 string)
  const sourceImages = Form.useWatch("source_images", form) ?? [];
  // 当前 picker 选中的 id 集合 — 第一次打开 picker 时,先按 Form.List
  // 已有 image id 集合初始化。
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerEditingIndex, setPickerEditingIndex] = useState<number | null>(null);

  // M36.1.1: audio / subtitle picker modal 状态。
  const [audioPickerOpen, setAudioPickerOpen] = useState(false);
  const [subtitlePickerOpen, setSubtitlePickerOpen] = useState(false);

  // M36.2.1: stock picker modal 状态。区别于 image picker,stock 走
  // ``/api/v1/stock-assets/{id}/image`` 路径,前端用 ``fetch + blob``
  // 模式预览(后端 Bearer 鉴权,见 MEMORY 2026-06-20)。
  const [stockPickerOpen, setStockPickerOpen] = useState(false);
  const [stockEditingIndex, setStockEditingIndex] = useState<number | null>(null);

  // M36.2.2: BGM picker modal 状态。跟 stock picker 同模式(fetch+blob),
  // 但 BGM 选完只填一个 input(没有列表追加语义)。
  const [musicPickerOpen, setMusicPickerOpen] = useState(false);

  // 解析当前 source_images 里所有 image id(URL 形态)给 picker 初始高亮。
  const currentImageIds = sourceImages
    .map((s: string) => parseImageId(s))
    .filter((x: number | undefined): x is number => x !== undefined);

  const createMut = useMutation({
    mutationFn: (values: any) => createVideoCompose(values),
    onSuccess: () => {
      message.success("提交成功 / Submitted");
      qc.invalidateQueries({ queryKey: ["videos"] });
      form.resetFields();
      onClose();
    },
    onError: (e: Error) => message.error(e.message),
  });

  // Reset on close — defensive belt-and-braces like image-generation's
  // CreateFormModal. destroyOnHidden already unmounts but resetFields
  // protects against reuse if parent lifts the form instance.
  useEffect(() => {
    if (!open) form.resetFields();
  }, [open, form]);

  // 处理 picker 选完图后的回调:
  //   - pickerEditingIndex !== null → 替换那一行
  //   - pickerEditingIndex === null → 追加到末尾
  const handlePickerConfirm = (ids: number[]) => {
    setPickerOpen(false);
    const urls = ids.map((id) => `${API_BASE}/api/v1/image-generation/${id}/image`);
    const current = form.getFieldValue("source_images") ?? [];
    if (pickerEditingIndex !== null) {
      // 替换模式(从 picker 选完后回到原行)
      const next = [...current];
      next[pickerEditingIndex] = urls[0] ?? "";
      form.setFieldValue("source_images", next);
    } else {
      // 追加模式
      form.setFieldValue("source_images", [...current, ...urls]);
    }
    setPickerEditingIndex(null);
  };

  // Stock picker 选完后,把 id 转成 ``/api/v1/stock-assets/{id}/image``
  // 代理 URL 写回 source_images。和 image picker 区分独立状态,避免
  // 双方"编辑模式/追加模式"互相污染。
  const handleStockPickerConfirm = (ids: number[]) => {
    setStockPickerOpen(false);
    const urls = ids.map(buildStockImageUrl);
    const current = form.getFieldValue("source_images") ?? [];
    if (stockEditingIndex !== null) {
      const next = [...current];
      next[stockEditingIndex] = urls[0] ?? "";
      form.setFieldValue("source_images", next);
    } else {
      form.setFieldValue("source_images", [...current, ...urls]);
    }
    setStockEditingIndex(null);
  };

  // 同上,识别 stock 库 URL 形态(append 模式需要给 stock picker 初始高亮)。
  function parseStockId(src: string): number | undefined {
    const m = src.match(/\/api\/v1\/stock-assets\/(\d+)\/image/);
    return m ? Number(m[1]) : undefined;
  }

  // 给 stock picker 的初始高亮 id 集合。
  const currentStockIds = sourceImages
    .map((s: string) => parseStockId(s))
    .filter((x: number | undefined): x is number => x !== undefined);

  return (
    <>
      <Modal
        open={open}
        title="新建视频合成"
        onCancel={onClose}
        footer={null}
        width={720}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={(v) => createMut.mutate(v)}
          initialValues={{
            resolution: "1280x720",
            fps: 24,
            audio_fade_in: 0,
            audio_fade_out: 0,
            source_images: [],
          }}
        >
          <Form.Item
            label="源图片 (至少 1 张)"
            required
            // 自定义校验:Form.List 非空
            rules={[
              {
                validator: async (_, value: string[] | undefined) => {
                  if (!value || value.length === 0) {
                    throw new Error("至少添加 1 张图片");
                  }
                },
              },
            ]}
          >
            <Form.List name="source_images">
              {(fields, { add, remove }) => (
                <>
                  {fields.map((field) => (
                    <div
                      key={field.key}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        marginBottom: 8,
                        gap: 8,
                      }}
                    >
                      <SourceImagePreview src={sourceImages[field.name] || ""} />
                      <Form.Item
                        {...field}
                        noStyle
                        // 用 Form.Item name 索引,value 即 source string
                        rules={[{ required: true, message: "请填写或选择图片" }]}
                      >
                        <Input
                          placeholder="/path/to/image.png 或 /api/v1/image-generation/N/image"
                          style={{ flex: 1 }}
                        />
                      </Form.Item>
                      <Button
                        icon={<AppstoreAddOutlined />}
                        onClick={() => {
                          setPickerEditingIndex(field.name);
                          setPickerOpen(true);
                        }}
                        title="从我的图片库选"
                      >
                        选
                      </Button>
                      <Button
                        danger
                        icon={<DeleteOutlined />}
                        onClick={() => remove(field.name)}
                        title="删除该行"
                      />
                    </div>
                  ))}
                  <Space>
                    <Button
                      type="dashed"
                      icon={<PlusOutlined />}
                      onClick={() => add("")}
                    >
                      添加图片路径
                    </Button>
                    <Button
                      icon={<AppstoreAddOutlined />}
                      onClick={() => {
                        setPickerEditingIndex(null);
                        setPickerOpen(true);
                      }}
                    >
                      从我的图片库选
                    </Button>
                    <Button
                      icon={<PictureOutlined />}
                      onClick={() => {
                        setStockEditingIndex(null);
                        setStockPickerOpen(true);
                      }}
                    >
                      从素材库选
                    </Button>
                  </Space>
                </>
              )}
            </Form.List>
          </Form.Item>

          {/* 注意 Form.Item + name + Space.Compact 子组件的坑:AntD 的
              Form.Item 用 cloneElement 把 value/onChange 注入**直接子**,
              Space.Compact 不是 input,导致 picker 调 setFieldValue 后
              input 显示不更新(form state 有值但 UI 是空的)。
              修法:Form.Item noStyle 包裹 Input,让 Input 直接接收
              value/onChange;外层用 Space.Compact 做视觉布局。 */}
          <Form.Item label="音频 (可选)">
            <Space.Compact style={{ width: "100%" }}>
              <Form.Item name="audio_path" noStyle>
                <Input
                  placeholder="本地路径 或 generated_audios.id (整数)"
                  style={{ width: "calc(100% - 160px)" }}
                />
              </Form.Item>
              <Button
                icon={<AudioOutlined />}
                onClick={() => setAudioPickerOpen(true)}
                style={{ width: 160 }}
              >
                从我的音频库选
              </Button>
            </Space.Compact>
          </Form.Item>
          <Form.Item
            label="字幕 (可选)"
            // 没 subtitle 时不展示错误红框(M36.1 阶段 1.1 仍允许留空)。
          >
            <Space.Compact style={{ width: "100%" }}>
              <Form.Item name="subtitle_path" noStyle rules={[]}>
                <Input
                  placeholder="本地 .srt/.vtt 路径 或 subtitles.id (整数)"
                  style={{ width: "calc(100% - 160px)" }}
                />
              </Form.Item>
              <Button
                icon={<FileTextOutlined />}
                onClick={() => setSubtitlePickerOpen(true)}
                style={{ width: 160 }}
              >
                从我的字幕库选
              </Button>
            </Space.Compact>
          </Form.Item>

          {/* M36.2.2: 背景音乐。跟 audio / subtitle 同模式:Input + 「从
              背景音乐库选」按钮。空值表示不加 BGM。schema 默认音量 0.3
              写在后端,UI 暂不暴露滑块。 */}
          <Form.Item label="背景音乐 (可选)">
            <Space.Compact style={{ width: "100%" }}>
              <Form.Item name="background_music_path" noStyle rules={[]}>
                <Input
                  placeholder="本地音频路径 或 stock_musics.id (整数)"
                  style={{ width: "calc(100% - 180px)" }}
                />
              </Form.Item>
              <Button
                icon={<CustomerServiceOutlined />}
                onClick={() => setMusicPickerOpen(true)}
                style={{ width: 180 }}
              >
                从背景音乐库选
              </Button>
            </Space.Compact>
          </Form.Item>

          <Form.Item name="playbook_id" label="Playbook (可选)">
            <PlaybookSelect scope="video" placeholder="选择 Playbook 自动注入风格" />
          </Form.Item>

          <details style={{ marginBottom: 16 }}>
            <summary style={{ cursor: "pointer", color: "#666" }}>
              高级参数 (Advanced)
            </summary>
            <div style={{ paddingTop: 12 }}>
              <Form.Item name="resolution" label="分辨率">
                <Select
                  virtual={false} // MEMORY 2026-06-08:小列表 + 自定义 → 关 virtual
                  options={[
                    { value: "1280x720", label: "1280 × 720 (720p)" },
                    { value: "1920x1080", label: "1920 × 1080 (1080p)" },
                    { value: "720x1280", label: "720 × 1280 (竖屏)" },
                    { value: "640x480", label: "640 × 480" },
                  ]}
                />
              </Form.Item>
              <Form.Item name="fps" label="帧率 (fps)">
                <Radio.Group
                  options={[
                    { value: 24, label: "24" },
                    { value: 30, label: "30" },
                    { value: 60, label: "60" },
                  ]}
                />
              </Form.Item>
              <Form.Item name="audio_fade_in" label="音频淡入 (秒)">
                <InputNumber min={0} max={10} step={0.1} style={{ width: 120 }} />
              </Form.Item>
              <Form.Item name="audio_fade_out" label="音频淡出 (秒)">
                <InputNumber min={0} max={10} step={0.1} style={{ width: 120 }} />
              </Form.Item>
              <Form.Item name="per_image_seconds" label="每张图时长 (秒,可选)">
                <InputNumber min={0.1} step={0.1} style={{ width: 120 }} />
              </Form.Item>
              <Form.Item name="subtitle_font" label="字幕字体 (可选)">
                <Input placeholder="如 Microsoft YaHei" />
              </Form.Item>
            </div>
          </details>

          <div style={{ textAlign: "right" }}>
            <Tag style={{ marginRight: 8 }}>
              共 {sourceImages.filter((s: string) => s).length} 张图
            </Tag>
            <Button onClick={onClose} style={{ marginRight: 8 }}>
              取消
            </Button>
            <Button
              type="primary"
              htmlType="submit"
              loading={createMut.isPending}
              disabled={sourceImages.length === 0}
            >
              提交合成
            </Button>
          </div>
        </Form>
      </Modal>

      <ImagePickerModal
        open={pickerOpen}
        initialSelected={currentImageIds}
        onClose={() => {
          setPickerOpen(false);
          setPickerEditingIndex(null);
        }}
        onConfirm={handlePickerConfirm}
      />
      <StockPickerModal
        open={stockPickerOpen}
        initialSelected={currentStockIds}
        onClose={() => {
          setStockPickerOpen(false);
          setStockEditingIndex(null);
        }}
        onConfirm={handleStockPickerConfirm}
      />
      <AudioPickerModal
        open={audioPickerOpen}
        onClose={() => setAudioPickerOpen(false)}
        onConfirm={(id) => {
          form.setFieldValue("audio_path", String(id));
          setAudioPickerOpen(false);
        }}
      />
      <SubtitlePickerModal
        open={subtitlePickerOpen}
        onClose={() => setSubtitlePickerOpen(false)}
        onConfirm={(id) => {
          form.setFieldValue("subtitle_path", String(id));
          setSubtitlePickerOpen(false);
        }}
      />
      <MusicPickerModal
        open={musicPickerOpen}
        initialSelected={null}
        onClose={() => setMusicPickerOpen(false)}
        onConfirm={(id) => {
          form.setFieldValue("background_music_path", String(id));
          setMusicPickerOpen(false);
        }}
      />
    </>
  );
}