// frontend/components/wx-publisher/AccountTable.tsx
// M32 — 公众号助手 — 公众号账号表格.
//
// Spec §5.6 — Table: 账号名 / AppID / 类型 Tag / Mock/Real Tag /
// 上次校验 / 状态 / 操作. 操作: [编辑] [校验 AppID] [切换 Mock/Real] [删除].
"use client";

import { Table, Tag, Button, Space, Switch, Popconfirm, Tooltip } from "antd";
import { EditOutlined, CheckCircleOutlined, DeleteOutlined } from "@ant-design/icons";
import type { WxAccountResponse } from "@/types/wx-publisher";

const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  subscription: "订阅号",
  service: "服务号",
  enterprise: "企业号",
};

const ACCOUNT_TYPE_COLORS: Record<string, string> = {
  subscription: "blue",
  service: "green",
  enterprise: "purple",
};

interface AccountTableProps {
  items: WxAccountResponse[];
  loading?: boolean;
  onEdit?: (account: WxAccountResponse) => void;
  onDelete?: (id: number) => void;
  onVerify?: (id: number) => void;
  onToggleMock?: (id: number, isMock: boolean) => void;
}

export function AccountTable({
  items,
  loading,
  onEdit,
  onDelete,
  onVerify,
  onToggleMock,
}: AccountTableProps) {
  return (
    <Table<WxAccountResponse>
      rowKey="id"
      dataSource={items}
      loading={loading}
      pagination={false}
      locale={{ emptyText: "暂无公众号账号" }}
      columns={[
        {
          title: "账号名",
          dataIndex: "name",
          key: "name",
        },
        {
          title: "AppID",
          dataIndex: "app_id",
          key: "app_id",
          render: (v: string) => (
            <code style={{ fontSize: 12 }}>{v}</code>
          ),
        },
        {
          title: "类型",
          dataIndex: "account_type",
          key: "account_type",
          render: (v: string) => (
            <Tag color={ACCOUNT_TYPE_COLORS[v] ?? "default"}>
              {ACCOUNT_TYPE_LABELS[v] ?? v}
            </Tag>
          ),
        },
        {
          title: "模式",
          dataIndex: "is_mock",
          key: "is_mock",
          render: (v: boolean, row) => (
            <Switch
              size="small"
              checked={v}
              checkedChildren="Mock"
              unCheckedChildren="Real"
              onChange={(checked) => onToggleMock?.(row.id, checked)}
            />
          ),
        },
        {
          title: "上次校验",
          dataIndex: "last_verified_at",
          key: "last_verified_at",
          render: (v: string | null) => (
            <span style={{ fontSize: 12, color: "#888" }}>
              {v ? new Date(v).toLocaleString() : "—"}
            </span>
          ),
        },
        {
          title: "状态",
          dataIndex: "is_active",
          key: "is_active",
          render: (v: boolean) =>
            v ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>,
        },
        {
          title: "操作",
          key: "actions",
          render: (_, row) => (
            <Space size={4}>
              {onEdit && (
                <Tooltip title="编辑">
                  <Button
                    type="link"
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => onEdit(row)}
                  />
                </Tooltip>
              )}
              {onVerify && (
                <Tooltip title="校验 AppID">
                  <Button
                    type="link"
                    size="small"
                    icon={<CheckCircleOutlined />}
                    onClick={() => onVerify(row.id)}
                  />
                </Tooltip>
              )}
              {onDelete && (
                <Popconfirm
                  title="确认停用该账号?"
                  okText="停用"
                  cancelText="取消"
                  onConfirm={() => onDelete(row.id)}
                >
                  <Button
                    type="link"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                  />
                </Popconfirm>
              )}
            </Space>
          ),
        },
      ]}
    />
  );
}

export default AccountTable;