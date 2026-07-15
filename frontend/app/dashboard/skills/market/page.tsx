"use client";

import { useState, useEffect } from "react";
import {
  Card, Table, Button, Tag, Space, Select, Rate,
  Drawer, Spin, App, Modal, Input, Alert,
} from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { skillsApi, skillAdminApi, MarketplaceSkill } from "@/services/skills";
import { SkillTypeTag } from "@/components/skills/SkillTypeTag";
import { SkillDetailContent } from "@/components/skills/detail";

export default function SkillsMarketPage() {
  // M15 (2026-06-09): 改用 App.useApp() 拿 message(项目 2026-06-07 铁律:
  // 静态 message import 在 React strict mode + App Router 下不渲染)
  const { message } = App.useApp();
  const [skills, setSkills] = useState<MarketplaceSkill[]>([]);
  const [loading, setLoading] = useState(false);
  const [category, setCategory] = useState<string | undefined>(undefined);
  const [installingId, setInstallingId] = useState<number | null>(null);
  // M15 详情查看 state
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detailData, setDetailData] = useState<MarketplaceSkill | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  // M17 test-run state
  const [testRunOpen, setTestRunOpen] = useState(false);
  const [testRunning, setTestRunning] = useState(false);
  const [testRunResult, setTestRunResult] = useState<any>(null);
  const [testRunInput, setTestRunInput] = useState("{}");

  const fetchSkills = async () => {
    setLoading(true);
    try {
      const response = await skillsApi.listMarketplace(category);
      if (response.data.code === 200) {
        // listMarketplace returns a PaginatedResponse; the array lives at
        // response.data.data (not response.data.data.skills).
        setSkills(Array.isArray(response.data.data) ? response.data.data : []);
      }
    } catch (error) {
      message.error("获取技能市场失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSkills();
  }, [category]);

  // M15: 详情 fetch effect —— detailId 变化时拉单条
  useEffect(() => {
    if (detailId === null) {
      setDetailData(null);
      return;
    }
    setDetailLoading(true);
    setDetailData(null);   // 切换时先清旧数据,避免上一个 skill 的 content 残留
    skillsApi
      .getMarketplaceSkill(detailId)
      .then((res) => {
        if (res.data.code === 200) {
          setDetailData(res.data.data);
        } else {
          message.error(res.data.message || "获取技能详情失败");
          setDetailId(null);
        }
      })
      .catch((err) => {
        message.error("获取技能详情失败");
        setDetailId(null);
      })
      .finally(() => {
        setDetailLoading(false);
      });
  }, [detailId]);

  const handleInstall = async (skill: MarketplaceSkill) => {
    setInstallingId(skill.id);
    try {
      const response = await skillsApi.installSkill(skill.id);
      if (response.data.code === 200) {
        message.success(`'${skill.name}' 安装成功`);
      }
    } catch (error) {
      message.error("安装失败");
    } finally {
      setInstallingId(null);
    }
  };

  // M17: test-run handler
  const handleTestRun = (skill: MarketplaceSkill) => {
    setDetailData(skill);
    setTestRunResult(null);
    setTestRunInput("{}");
    setTestRunOpen(true);
  };

  const submitTestRun = async () => {
    if (!detailData) return;
    let inputArgs: Record<string, any> = {};
    try {
      inputArgs = JSON.parse(testRunInput);
    } catch (e) {
      message.error("输入参数 JSON 解析失败");
      return;
    }
    setTestRunning(true);
    try {
      const res = await skillAdminApi.testRun(detailData.id, inputArgs);
      if (res.data.code === 200) {
        setTestRunResult(res.data.data);
        message.success("测试运行完成");
      } else {
        message.error(res.data.message || "测试运行失败");
      }
    } catch (e) {
      message.error("测试运行失败");
    } finally {
      setTestRunning(false);
    }
  };

  const columns = [
    { title: "名称", dataIndex: "name", key: "name" },
    {
      title: "类型",
      dataIndex: "type",
      key: "type",
      render: (t: string | undefined) => <SkillTypeTag type={t} />,
    },
    { title: "分类", dataIndex: "category", key: "category", render: (cat: string) => <Tag>{cat}</Tag> },
    { title: "描述", dataIndex: "description", key: "description" },
    { title: "下载", dataIndex: "downloads", key: "downloads" },
    { title: "评分", dataIndex: "rating", key: "rating", render: (r: number) => <Rate disabled defaultValue={r} /> },
    {
      title: "操作",
      key: "action",
      render: (_: any, record: MarketplaceSkill) => (
        <Space>
          <Button
            type="link"
            size="small"
            onClick={() => setDetailId(record.id)}
          >
            详情
          </Button>
          <Button
            type="primary"
            size="small"
            icon={<DownloadOutlined />}
            loading={installingId === record.id}
            onClick={() => handleInstall(record)}
            disabled={record.is_installed}
          >
            {record.is_installed ? "已安装" : "安装"}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Card
        title="技能市场"
        extra={
          <Select
            placeholder="选择分类"
            allowClear
            onChange={(v) => setCategory(v)}
            style={{ width: 200 }}
            options={[
              { value: "code", label: "代码" },
              { value: "writing", label: "写作" },
              { value: "data", label: "数据" },
              { value: "testing", label: "测试" },
              { value: "design", label: "设计" },
            ]}
          />
        }
      >
        <Table
          columns={columns}
          dataSource={skills}
          rowKey="id"
          loading={loading}
        />
      </Card>

      <Drawer
        title={
          detailData ? (
            <Space>
              {detailData.name}
              <SkillTypeTag type={detailData.type} />
            </Space>
          ) : null
        }
        open={detailId !== null}
        onClose={() => setDetailId(null)}
        width={560}
        destroyOnHidden
        footer={
          detailData && (
            <Space style={{ width: "100%", justifyContent: "flex-end" }}>
              <Button onClick={() => setDetailId(null)}>关闭</Button>
              <Button onClick={() => handleTestRun(detailData)} loading={testRunning}>
                测试运行
              </Button>
              {detailData.is_installed ? (
                <Tag color="green" style={{ margin: 0 }}>已安装</Tag>
              ) : (
                <Button
                  type="primary"
                  icon={<DownloadOutlined />}
                  loading={installingId === detailData.id}
                  onClick={() => handleInstall(detailData)}
                >
                  安装
                </Button>
              )}
            </Space>
          )
        }
      >
        {detailLoading || !detailData ? (
          <div style={{ display: "flex", justifyContent: "center", padding: 48 }}>
            <Spin />
          </div>
        ) : (
          <SkillDetailContent skill={detailData} />
        )}
      </Drawer>

      {/* M17 test-run modal */}
      <Modal
        title={`测试运行 — ${detailData?.name ?? ""}`}
        open={testRunOpen}
        onCancel={() => setTestRunOpen(false)}
        onOk={submitTestRun}
        confirmLoading={testRunning}
        okText="运行"
        cancelText="取消"
        width={600}
      >
        <div style={{ marginBottom: 12 }}>
          <strong>输入参数 (JSON):</strong>
          <Input.TextArea
            rows={4}
            value={testRunInput}
            onChange={(e) => setTestRunInput(e.target.value)}
            placeholder='{"topic": "Python"}'
            style={{ fontFamily: "Menlo, Consolas, monospace", marginTop: 4 }}
          />
        </div>
        {testRunResult && (
          <Alert
            type={testRunResult.error ? "error" : "success"}
            showIcon
            message={`耗时: ${testRunResult.latency_ms}ms — 类型: ${testRunResult.type}`}
            description={
              <pre
                style={{
                  background: "#f5f5f5", border: "1px solid #e8e8e8", borderRadius: 4,
                  padding: 8, fontSize: 11, fontFamily: "Menlo, Consolas, monospace",
                  whiteSpace: "pre-wrap", wordBreak: "break-word", margin: 0,
                  maxHeight: 300, overflow: "auto",
                }}
              >
                {testRunResult.error
                  ? `Error: ${testRunResult.error}`
                  : JSON.stringify(testRunResult.result, null, 2)}
              </pre>
            }
          />
        )}
      </Modal>
    </div>
  );
}
