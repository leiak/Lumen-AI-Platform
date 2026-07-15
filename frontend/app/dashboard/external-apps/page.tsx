"use client";

import { useState, useEffect } from "react";
import {
  Table,
  Button,
  Space,
  Switch,
  Tag,
  Popconfirm,
  App,
} from "antd";
import {
  PlusOutlined,
  ReloadOutlined,
  EditOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { externalAppApi } from "@/services/externalApp";
import type { ExternalApp } from "@/types/api";

export default function ExternalAppsPage() {
  // MEMORY.md pitfall: antd v5 + Next.js 15 App Router static `message`
  // import does NOT render under React strict mode. Use App.useApp() —
  // the dashboard layout already wraps children in <App>.
  const { message: msgApi } = App.useApp();
  const router = useRouter();
  const [items, setItems] = useState<ExternalApp[]>([]);
  const [loading, setLoading] = useState(false);
  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 20,
    total: 0,
  });

  async function load(page = 1) {
    setLoading(true);
    try {
      const res = await externalAppApi.list({
        page,
        page_size: pagination.pageSize,
      });
      setItems(res.items);
      setPagination((p) => ({
        ...p,
        current: res.page,
        total: res.total,
      }));
    } catch (e: any) {
      msgApi.error(`加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function toggleActive(app: ExternalApp, checked: boolean) {
    // Optimistic update: flip the row's is_active immediately so the
    // Switch feels responsive, then revert if the API rejects.
    setItems((prev) =>
      prev.map((a) => (a.id === app.id ? { ...a, is_active: checked } : a))
    );
    try {
      await externalAppApi.update(app.id, { is_active: checked });
    } catch (e: any) {
      msgApi.error(`切换失败: ${e?.message ?? e}`);
      // Rollback to the previous is_active value.
      setItems((prev) =>
        prev.map((a) => (a.id === app.id ? { ...a, is_active: !checked } : a))
      );
    }
  }

  async function handleDelete(id: number) {
    try {
      await externalAppApi.remove(id);
      msgApi.success("已删除");
      load(pagination.current);
    } catch (e: any) {
      // 409 = backend refuses (likely active sessions on the app).
      // Surface the specific Chinese message; fall back to a generic
      // error for anything else.
      if (e?.response?.status === 409) {
        msgApi.error("该应用还有活跃会话,请先停用或导出后清理");
      } else {
        msgApi.error(`删除失败: ${e?.message ?? e}`);
      }
    }
  }

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>外部应用授权</h2>
        <Button
          icon={<ReloadOutlined />}
          onClick={() => load(pagination.current)}
        >
          刷新
        </Button>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => router.push("/dashboard/external-apps/new")}
        >
          新建应用
        </Button>
      </Space>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={items}
        pagination={{
          current: pagination.current,
          pageSize: pagination.pageSize,
          total: pagination.total,
          onChange: (p) => load(p),
        }}
        columns={[
          { title: "名称", dataIndex: "name" },
          {
            title: "App Key",
            dataIndex: "app_key",
            render: (k: string) => <code>{k.slice(0, 16)}…</code>,
          },
          {
            title: "授权 Agent",
            dataIndex: "allowed_agent_names",
            render: (ns: string[]) =>
              ns.length
                ? ns
                    .slice(0, 3)
                    .map((n) => <Tag key={n}>{n}</Tag>)
                    .concat(
                      ns.length > 3
                        ? [<Tag key="more">+{ns.length - 3}</Tag>]
                        : []
                    )
                : "—",
          },
          {
            title: "Origins",
            dataIndex: "allowed_origins",
            render: (os: string[]) =>
              os.length
                ? os
                    .slice(0, 2)
                    .map((o) => <Tag key={o}>{o}</Tag>)
                    .concat(
                      os.length > 2
                        ? [<Tag key="more">+{os.length - 2}</Tag>]
                        : []
                    )
                : "—",
          },
          {
            title: "速率",
            dataIndex: "rate_limit_per_min",
            render: (n: number) => `${n}/min`,
          },
          {
            title: "状态",
            dataIndex: "is_active",
            render: (v: boolean, r: ExternalApp) => (
              <Switch checked={v} onChange={(c) => toggleActive(r, c)} />
            ),
          },
          {
            title: "操作",
            render: (_: any, r: ExternalApp) => (
              <Space>
                <Link href={`/dashboard/external-apps/${r.id}`}>
                  <Button size="small" icon={<EditOutlined />}>
                    编辑
                  </Button>
                </Link>
                <Popconfirm
                  title="确定删除?"
                  onConfirm={() => handleDelete(r.id)}
                >
                  <Button size="small" danger icon={<DeleteOutlined />}>
                    删除
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
    </div>
  );
}
