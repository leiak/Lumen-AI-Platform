"use client";

import { Input, Select, Space, Button } from "antd";
import { SearchOutlined, ReloadOutlined } from "@ant-design/icons";

interface Props {
  search: string;
  isActive: boolean | undefined;
  onSearchChange: (v: string) => void;
  onActiveChange: (v: boolean | undefined) => void;
  onRefresh: () => void;
}

/**
 * M30b: search + active/inactive filter bar that lives above the
 * workflow table. Wired to /workflows/?search=...&is_active=...
 * (M30a server-side search/filter).
 */
export function SearchFilterBar({
  search,
  isActive,
  onSearchChange,
  onActiveChange,
  onRefresh,
}: Props) {
  return (
    <Space wrap style={{ marginBottom: 16 }}>
      <Input
        placeholder="搜索工作流"
        allowClear
        prefix={<SearchOutlined />}
        value={search}
        onChange={(e) => onSearchChange(e.target.value)}
        style={{ width: 280 }}
      />
      <Select
        placeholder="状态"
        allowClear
        value={isActive}
        onChange={onActiveChange}
        style={{ width: 140 }}
        options={[
          { label: "启用", value: true },
          { label: "禁用", value: false },
        ]}
      />
      <Button icon={<ReloadOutlined />} onClick={onRefresh}>
        刷新
      </Button>
    </Space>
  );
}
