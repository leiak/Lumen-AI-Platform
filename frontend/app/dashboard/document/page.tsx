"use client";

import { useState } from "react";
import { Card, Input, Button, Space, message } from "antd";

const { TextArea } = Input;

export default function DocumentPage() {
  const [title, setTitle] = useState("文档标题");
  const [content, setContent] = useState("这是文档内容...\n\n可以多段落。");
  const [loading, setLoading] = useState(false);

  const generateWord = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:3005/api/v1"}/documents/generate/word?title=${encodeURIComponent(title)}&content=${encodeURIComponent(content)}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` }
      });
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${title}.docx`;
      a.click();
      message.success("Word 文档已生成");
    } catch (error) {
      message.error("生成失败");
    } finally {
      setLoading(false);
    }
  };

  const generateExcel = async () => {
    setLoading(true);
    try {
      const sampleData = [
        { 姓名: "张三", 年龄: 25, 城市: "北京" },
        { 姓名: "李四", 年龄: 30, 城市: "上海" },
        { 姓名: "王五", 年龄: 28, 城市: "广州" },
      ];
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:3005/api/v1"}/documents/generate/excel?data=${encodeURIComponent(JSON.stringify(sampleData))}&filename=${encodeURIComponent("示例数据")}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` }
      });
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "示例数据.xlsx";
      a.click();
      message.success("Excel 文档已生成");
    } catch (error) {
      message.error("生成失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Card title="文档生成">
        <Space direction="vertical" style={{ width: "100%" }} size="large">
          <Input
            placeholder="文档标题"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <TextArea
            rows={10}
            placeholder="文档内容"
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
          <Space>
            <Button type="primary" onClick={generateWord} loading={loading}>
              生成 Word 文档
            </Button>
            <Button onClick={generateExcel} loading={loading}>
              生成 Excel 文档
            </Button>
          </Space>
        </Space>
      </Card>
    </div>
  );
}