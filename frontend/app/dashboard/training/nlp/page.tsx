"use client";

import { useEffect, useState } from "react";
import { Card, Row, Col, Statistic, Spin, Tag, Space, Button, message } from "antd";
import {
  BookOutlined,
  FileTextOutlined,
  MessageOutlined,
  AppstoreOutlined,
  RightOutlined,
} from "@ant-design/icons";
import { useRouter } from "next/navigation";
import { nlpApi, NLPClassification, NLPAnnotation, NLPQA } from "@/services/nlp";

interface SubCard {
  title: string;
  desc: string;
  icon: React.ReactNode;
  href: string;
  count?: number;
  color: string;
}

export default function NLPLandingPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [classifications, setClassifications] = useState<NLPClassification[]>([]);
  const [annotations, setAnnotations] = useState<NLPAnnotation[]>([]);
  const [qa, setQA] = useState<NLPQA[]>([]);
  // Real server-side counts. We use page_size=1 above for the cheap
  // request, but the dashboard needs the actual totals — `array.length`
  // would always read 1 and make every stat card show "1".
  const [classificationsTotal, setClassificationsTotal] = useState(0);
  const [annotationsTotal, setAnnotationsTotal] = useState(0);
  const [qaTotal, setQATotal] = useState(0);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [c, a, q] = await Promise.all([
          nlpApi.listClassifications(1, 1).catch(() => null),
          nlpApi.listAnnotations(undefined, 1, 1).catch(() => null),
          nlpApi.listQA(1, 1).catch(() => null),
        ]);
        if (c?.data?.code === 200) {
          setClassifications(c.data.data || []);
          setClassificationsTotal(c.data.total || (c.data.data || []).length);
        }
        if (a?.data?.code === 200) {
          setAnnotations(a.data.data || []);
          setAnnotationsTotal(a.data.total || (a.data.data || []).length);
        }
        if (q?.data?.code === 200) {
          setQA(q.data.data || []);
          setQATotal(q.data.total || (q.data.data || []).length);
        }
      } catch (error) {
        message.error("加载 NLP 概览失败");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const cards: SubCard[] = [
    {
      title: "文本数据集",
      desc: "导入并管理训练用的文本语料，每个文本绑定到目标分类。",
      icon: <FileTextOutlined />,
      href: "/dashboard/training/nlp/annotation",
      color: "#1677ff",
    },
    {
      title: "分类训练",
      desc: "创建分类、配置超参数、训练 TF-IDF + LR 文本分类模型并评估。",
      icon: <AppstoreOutlined />,
      href: "/dashboard/training/nlp/classification",
      color: "#52c41a",
    },
    {
      title: "问答管理",
      desc: "维护问答对 (Q&A) 数据，用于问答场景训练或检索。",
      icon: <MessageOutlined />,
      href: "/dashboard/training/nlp/qa",
      color: "#722ed1",
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Card title="NLP 训练中心" extra={<Tag color="blue">自然语言处理</Tag>}>
        <Spin spinning={loading}>
          <Row gutter={16}>
            <Col span={8}>
              <Statistic
                title="分类数"
                value={classificationsTotal}
                prefix={<AppstoreOutlined style={{ color: "#52c41a" }} />}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="文本数据集条目"
                value={annotationsTotal}
                prefix={<FileTextOutlined style={{ color: "#1677ff" }} />}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="问答对"
                value={qaTotal}
                prefix={<MessageOutlined style={{ color: "#722ed1" }} />}
              />
            </Col>
          </Row>
        </Spin>
        <p style={{ marginTop: 16, color: "#666" }}>
          <BookOutlined /> 先准备数据，再配置超参数启动训练，最后用预测验证效果。
        </p>
      </Card>

      <Row gutter={16} style={{ marginTop: 16 }}>
        {cards.map((c) => (
          <Col span={8} key={c.href}>
            <Card
              hoverable
              onClick={() => router.push(c.href)}
              style={{ borderColor: c.color }}
            >
              <Space align="start">
                <div
                  style={{
                    fontSize: 28,
                    color: c.color,
                    background: `${c.color}15`,
                    padding: 12,
                    borderRadius: 8,
                  }}
                >
                  {c.icon}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 16, fontWeight: 600 }}>{c.title}</div>
                  <div style={{ color: "#888", marginTop: 4 }}>{c.desc}</div>
                </div>
                <Button type="link" icon={<RightOutlined />}>
                  进入
                </Button>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}
