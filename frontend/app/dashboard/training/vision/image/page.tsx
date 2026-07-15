"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Card,
  Button,
  Select,
  Space,
  Tag,
  Empty,
  Progress,
  message,
  Popconfirm,
  Input,
  Tooltip,
} from "antd";
import {
  UploadOutlined,
  ReloadOutlined,
  DeleteOutlined,
  SearchOutlined,
  PictureOutlined,
  ClearOutlined,
} from "@ant-design/icons";
import type { UploadProps } from "antd";
import {
  visionApi,
  VisionClassification,
  VisionImage,
  PendingImage,
  createImagePreviewUrl,
  revokeImagePreviewUrl,
} from "@/services/vision";

const PAGE_SIZE = 200;

export default function VisionImagePage() {
  const [classifications, setClassifications] = useState<VisionClassification[]>([]);
  const [images, setImages] = useState<VisionImage[]>([]);
  // Real server-side count for the current classification. We cap the
  // fetch at PAGE_SIZE rows but still want the gallery header to show
  // the true total and warn when results were truncated.
  const [imagesTotal, setImagesTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [selectedClassification, setSelectedClassification] = useState<number | undefined>();
  const [keyword, setKeyword] = useState("");
  const [pending, setPending] = useState<PendingImage[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const fetchClassifications = useCallback(async () => {
    try {
      const res = await visionApi.listClassifications(1, 100);
      if (res.data?.code === 200) {
        setClassifications(res.data.data || []);
      } else {
        message.error(res.data?.message || "获取分类列表失败");
      }
    } catch (error: any) {
      message.error(error?.response?.data?.message || "获取分类列表失败");
    }
  }, []);

  const fetchImages = useCallback(async () => {
    if (selectedClassification == null) {
      setImages([]);
      setImagesTotal(0);
      return;
    }
    setLoading(true);
    try {
      const res = await visionApi.listImages(selectedClassification, 1, PAGE_SIZE);
      if (res.data?.code === 200) {
        setImages(res.data.data || []);
        setImagesTotal(res.data.total || (res.data.data || []).length);
      } else {
        message.error(res.data?.message || "获取图片列表失败");
      }
    } catch (error: any) {
      message.error(error?.response?.data?.message || "获取图片列表失败");
    } finally {
      setLoading(false);
    }
  }, [selectedClassification]);

  useEffect(() => {
    fetchClassifications();
  }, [fetchClassifications]);

  useEffect(() => {
    fetchImages();
  }, [fetchImages]);

  // Release preview URLs on unmount.
  useEffect(() => {
    return () => {
      pending.forEach((p) => revokeImagePreviewUrl(p.previewUrl));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFiles = (files: File[]) => {
    if (selectedClassification == null) {
      message.warning("请先选择目标分类");
      return;
    }
    const allowedTypes = ["image/jpeg", "image/png", "image/webp", "image/gif"];
    const accepted: PendingImage[] = [];
    const rejected: string[] = [];
    for (const f of files) {
      if (!allowedTypes.includes(f.type)) {
        rejected.push(f.name);
        continue;
      }
      if (f.size > 10 * 1024 * 1024) {
        rejected.push(`${f.name} (>10MB)`);
        continue;
      }
      accepted.push({
        uid: `${Date.now()}-${f.name}-${Math.random().toString(36).slice(2, 7)}`,
        file: f,
        previewUrl: createImagePreviewUrl(f),
      });
    }
    if (rejected.length > 0) {
      message.warning(`已跳过 ${rejected.length} 个文件（类型/大小不支持）`);
    }
    if (accepted.length > 0) {
      setPending((prev) => [...prev, ...accepted]);
    }
  };

  const removePending = (uid: string) => {
    setPending((prev) => {
      const target = prev.find((p) => p.uid === uid);
      if (target) revokeImagePreviewUrl(target.previewUrl);
      return prev.filter((p) => p.uid !== uid);
    });
  };

  const clearPending = () => {
    pending.forEach((p) => revokeImagePreviewUrl(p.previewUrl));
    setPending([]);
  };

  const uploadAll = async () => {
    if (selectedClassification == null) {
      message.warning("请先选择目标分类");
      return;
    }
    if (pending.length === 0) {
      message.warning("请先选择图片");
      return;
    }
    setUploading(true);
    setUploadProgress(0);
    let successCount = 0;
    let failCount = 0;
    for (let i = 0; i < pending.length; i += 1) {
      const item = pending[i];
      try {
        const res = await visionApi.uploadImage(selectedClassification, item.file);
        if (res.data?.code === 200) {
          successCount += 1;
        } else {
          failCount += 1;
        }
      } catch {
        failCount += 1;
      }
      setUploadProgress(Math.round(((i + 1) / pending.length) * 100));
    }
    pending.forEach((p) => revokeImagePreviewUrl(p.previewUrl));
    setPending([]);
    setUploading(false);
    setUploadProgress(0);
    if (successCount > 0) {
      message.success(
        `上传完成：成功 ${successCount} 张${failCount > 0 ? `, 失败 ${failCount} 张` : ""}`,
      );
      await fetchImages();
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
        await fetchImages();
      } else {
        message.error(res.data?.message || "删除失败");
      }
    } catch (error: any) {
      message.error(error?.response?.data?.message || "删除失败");
    } finally {
      setDeletingId(null);
    }
  };

  const filteredImages = keyword
    ? images.filter((i) => i.filename.toLowerCase().includes(keyword.toLowerCase()))
    : images;

  const totalBytes = pending.reduce((s, p) => s + p.file.size, 0);

  const uploadProps: UploadProps = {
    accept: "image/jpeg,image/png,image/webp,image/gif",
    multiple: true,
    showUploadList: false,
    beforeUpload: (file, fileList) => {
      // Collect every file in this dialog selection (dragged or clicked).
      handleFiles(fileList.length > 0 ? fileList : [file]);
      return false;
    },
  };

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={
          <Space>
            <PictureOutlined />
            <span>图像管理</span>
            {selectedClassification != null && (
              <Tag color="blue">
                {filteredImages.length} / {imagesTotal} 张
              </Tag>
            )}
            {pending.length > 0 && <Tag color="orange">待上传 {pending.length}</Tag>}
          </Space>
        }
        extra={
          <Space>
            <Select
              placeholder="选择分类"
              allowClear
              style={{ width: 220 }}
              value={selectedClassification}
              onChange={(v) => setSelectedClassification(v)}
              options={classifications.map((c) => ({ value: c.id, label: c.name }))}
            />
            <Button
              icon={<ReloadOutlined />}
              onClick={fetchImages}
              loading={loading}
              disabled={selectedClassification == null}
            >
              刷新
            </Button>
          </Space>
        }
      >
        {/* Upload bar */}
        <Space style={{ marginBottom: 16 }} wrap>
          <Button
            type="primary"
            icon={<UploadOutlined />}
            onClick={uploadAll}
            disabled={selectedClassification == null || pending.length === 0}
            loading={uploading}
          >
            上传图片 {pending.length > 0 ? `(${pending.length})` : ""}
          </Button>
          <Button {...(uploadProps as any)} icon={<UploadOutlined />}>
            选择文件
          </Button>
          {pending.length > 0 && (
            <Button icon={<ClearOutlined />} onClick={clearPending} disabled={uploading}>
              清空待上传
            </Button>
          )}
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder="按文件名搜索"
            style={{ width: 220 }}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            disabled={selectedClassification == null}
          />
          {pending.length > 0 && (
            <span style={{ color: "#666", fontSize: 12 }}>
              待上传：{pending.length} 张 / {(totalBytes / 1024).toFixed(1)} KB
            </span>
          )}
        </Space>

        {uploading && (
          <Progress
            percent={uploadProgress}
            status="active"
            style={{ marginBottom: 16 }}
            format={(p) => `上传中 ${p}%`}
          />
        )}

        {selectedClassification != null && imagesTotal > PAGE_SIZE && (
          <div
            style={{
              marginBottom: 16,
              padding: "8px 12px",
              background: "#fffbe6",
              border: "1px solid #ffe58f",
              borderRadius: 4,
              fontSize: 12,
              color: "#874d00",
            }}
          >
            当前仅展示前 {PAGE_SIZE} 张（共 {imagesTotal} 张）。如需查看更多，请在「训练」页面分批使用。
          </div>
        )}

        {/* Pending previews */}
        {pending.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 13, color: "#666", marginBottom: 8 }}>待上传预览</div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(110px, 1fr))",
                gap: 10,
              }}
            >
              {pending.map((p) => (
                <div
                  key={p.uid}
                  style={{
                    position: "relative",
                    border: "1px dashed #faad14",
                    borderRadius: 6,
                    padding: 4,
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
                      fontSize: 11,
                      marginTop: 4,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {p.file.name}
                  </div>
                  <div style={{ fontSize: 10, color: "#d48806" }}>
                    {(p.file.size / 1024).toFixed(1)} KB
                  </div>
                  <Button
                    size="small"
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => removePending(p.uid)}
                    disabled={uploading}
                    style={{ position: "absolute", top: 2, right: 2 }}
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Uploaded gallery */}
        {selectedClassification == null ? (
          <Empty description="请先选择目标分类" />
        ) : filteredImages.length === 0 && !loading ? (
          <Empty description="该分类下暂无图片" />
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
              gap: 12,
            }}
          >
            {filteredImages.map((img) => (
              <div
                key={img.id}
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
                  <PictureOutlined style={{ fontSize: 36, color: "#bfbfbf" }} />
                </div>
                <Tooltip title={img.filename}>
                  <div
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
                </Tooltip>
                <div style={{ fontSize: 11, color: "#999" }}>ID: {img.id}</div>
                <Popconfirm title="确认删除该图片?" onConfirm={() => handleDelete(img.id)}>
                  <Button
                    size="small"
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    loading={deletingId === img.id}
                    style={{ position: "absolute", top: 4, right: 4 }}
                  />
                </Popconfirm>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
