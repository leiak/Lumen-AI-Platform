"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Card,
  Table,
  Button,
  Tag,
  Space,
  Popconfirm,
  Empty,
  Rate,
  App,
} from "antd";
import {
  UnorderedListOutlined,
  ShopOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import { skillsApi, type InstalledSkill } from "@/services/skills";

export default function InstalledSkillsPage() {
  const router = useRouter();
  const { message } = App.useApp();  // M20: 项目铁律,用 App.useApp() 拿 message
  const [skills, setSkills] = useState<InstalledSkill[]>([]);
  const [loading, setLoading] = useState(false);
  const [uninstallingId, setUninstallingId] = useState<number | null>(null);
  // M20: 服务端分页 + 批量卸载
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [total, setTotal] = useState(0);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [batchUninstalling, setBatchUninstalling] = useState(false);
  const reqIdRef = useRef(0);

  const fetchInstalled = async (page: number, size: number) => {
    const myId = ++reqIdRef.current;
    setLoading(true);
    try {
      const res = await skillsApi.listInstalled(page, size);
      if (myId !== reqIdRef.current) return; // a newer request superseded this one
      if (res.data.code === 200) {
        // listInstalled returns a PaginatedResponse; `data` IS the array,
        // not an object wrapping the array.
        const list = Array.isArray(res.data.data) ? res.data.data : [];
        setSkills(list);
        setTotal(res.data.total ?? 0);
        // NOTE: do NOT echo page/page_size back to state — it would
        // retrigger the [currentPage, pageSize] useEffect and cause
        // double fetches. The user-controlled state is the source of truth.
      } else {
        message.error(res.data.message || "加载已装技能失败");
      }
    } catch (err) {
      if (myId !== reqIdRef.current) return;
      message.error("加载已装技能失败");
    } finally {
      if (myId === reqIdRef.current) setLoading(false);
    }
  };

  useEffect(() => {
    fetchInstalled(currentPage, pageSize);
    return () => {
      reqIdRef.current++; // invalidate any in-flight request on unmount
    };
  }, [currentPage, pageSize]);

  const handleUninstall = async (record: InstalledSkill) => {
    setUninstallingId(record.id);
    try {
      const res = await skillsApi.uninstallSkill(record.id);
      if (res.data.code === 200) {
        message.success(`已卸载 ${record.name}`);
        await fetchInstalled(currentPage, pageSize);
      } else {
        message.error(res.data.message || "卸载失败");
      }
    } catch (err) {
      message.error("卸载失败");
    } finally {
      setUninstallingId(null);
    }
  };

  // M20: 批量卸载
  const handleBatchUninstall = async () => {
    setBatchUninstalling(true);
    try {
      const ids = selectedRowKeys.map((k) => Number(k));
      const res = await skillsApi.batchUninstall(ids);
      if (res.data.code === 200) {
        const { succeeded_count, failed } = res.data.data ?? {};
        if (failed && failed.length > 0) {
          message.warning(
            `已卸载 ${succeeded_count} 项,${failed.length} 项失败(可能未安装)`
          );
        } else {
          message.success(`已卸载 ${succeeded_count} 项`);
        }
        setSelectedRowKeys([]);
        // 当前页被清空 → 翻回前一页
        if (skills.length - (succeeded_count ?? 0) <= 0 && currentPage > 1) {
          setCurrentPage(currentPage - 1);
        } else {
          await fetchInstalled(currentPage, pageSize);
        }
      } else {
        message.error(res.data.message || "批量卸载失败");
      }
    } catch (err) {
      message.error("批量卸载失败");
    } finally {
      setBatchUninstalling(false);
    }
  };

  const columns = [
    { title: "名称", dataIndex: "name", key: "name" },
    {
      title: "分类",
      dataIndex: "category",
      key: "category",
      render: (cat: string) => <Tag>{cat}</Tag>,
    },
    { title: "版本", dataIndex: "version", key: "version" },
    { title: "描述", dataIndex: "description", key: "description" },
    {
      title: "评分",
      dataIndex: "rating",
      key: "rating",
      render: (r: string | null | undefined) =>
        r == null ? "-" : <Rate disabled allowHalf defaultValue={Number(r)} />,
    },
    {
      title: "操作",
      key: "action",
      render: (_: any, record: InstalledSkill) => (
        <Popconfirm
          title="确认卸载此技能?"
          okText="卸载"
          cancelText="取消"
          onConfirm={() => handleUninstall(record)}
        >
          <Button
            danger
            size="small"
            loading={uninstallingId === record.id}
          >
            卸载
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={
          <Space>
            <UnorderedListOutlined />
            我的技能
            {selectedRowKeys.length > 0 && (
              <Tag color="blue" data-testid="selected-count">
                已选 {selectedRowKeys.length} 项
              </Tag>
            )}
          </Space>
        }
        extra={
          <Space>
            {selectedRowKeys.length > 0 && (
              <Popconfirm
                title={`确认卸载选中的 ${selectedRowKeys.length} 项技能?`}
                description="此操作不可撤销"
                okText="卸载"
                okButtonProps={{ danger: true }}
                cancelText="取消"
                onConfirm={handleBatchUninstall}
              >
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  loading={batchUninstalling}
                  data-testid="batch-uninstall-btn"
                >
                  批量卸载
                </Button>
              </Popconfirm>
            )}
            <Button
              icon={<ShopOutlined />}
              onClick={() => router.push("/dashboard/skills/market")}
            >
              去市场安装
            </Button>
          </Space>
        }
      >
        <Table
          columns={columns}
          dataSource={skills}
          rowKey={(r) => r.skill_id ?? r.id}
          loading={loading}
          pagination={{
            current: currentPage,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 项`,
            onChange: (p, s) => {
              setCurrentPage(p);
              setPageSize(s);
            },
          }}
          rowSelection={{
            selectedRowKeys,
            onChange: (keys) => setSelectedRowKeys(keys),
          }}
          locale={{
            emptyText: (
              <Empty
                description="尚未安装任何技能"
                style={{ padding: 24 }}
              >
                <Button
                  type="primary"
                  onClick={() => router.push("/dashboard/skills/market")}
                >
                  去市场看看
                </Button>
              </Empty>
            ),
          }}
        />
      </Card>
    </div>
  );
}
