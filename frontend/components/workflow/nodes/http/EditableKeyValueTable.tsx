"use client";

/**
 * M30c: editable key-value table for HTTP Headers / Query Params.
 *
 * Replaces the read-only AntD Table that the pre-M30c HTTPPanel used
 * (which had no onChange / no add / no delete buttons, so users
 * literally could not add a header from the UI — only see the empty
 * placeholder). The component:
 *   - renders a list of {key, value} rows
 *   - lets the user add a new row, edit existing cells, or delete a row
 *   - on every change calls `onChange(next: Record<string, string>)`
 *
 * The onChange contract matches `HTTPNodeConfig.headers` and
 * `HTTPNodeConfig.query_params` — both are `Record<string, string>`.
 */
import { Button, Input, Space, Table } from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { useState } from "react";

interface Props {
  value?: Record<string, string>;
  onChange?: (next: Record<string, string>) => void;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
}

interface Row {
  key: string; // antd row key — must be unique. We use the entry's *key* string
  // (the header / param name). To allow editing the key we keep the
  // original key in `_origKey` until commit.
  _origKey: string;
  name: string;
  value: string;
}

function toRows(value: Record<string, string> | undefined): Row[] {
  return Object.entries(value ?? {}).map(([k, v]) => ({
    key: k,
    _origKey: k,
    name: k,
    value: v,
  }));
}

function fromRows(rows: Row[]): Record<string, string> {
  // Filter out rows with an empty key (invalid) and use the row's
  // current `name` as the new key.
  const out: Record<string, string> = {};
  for (const r of rows) {
    const k = r.name.trim();
    if (!k) continue;
    out[k] = r.value;
  }
  return out;
}

export function EditableKeyValueTable({
  value,
  onChange,
  keyPlaceholder = "Key",
  valuePlaceholder = "Value",
}: Props) {
  const [rows, setRows] = useState<Row[]>(() => toRows(value));

  const commit = (next: Row[]) => {
    setRows(next);
    onChange?.(fromRows(next));
  };

  const handleAdd = () => {
    // Find a unique placeholder key.
    let n = 1;
    let placeholder = `key-${n}`;
    const taken = new Set(rows.map((r) => r.name));
    while (taken.has(placeholder)) {
      n += 1;
      placeholder = `key-${n}`;
    }
    commit([...rows, { key: placeholder, _origKey: "", name: placeholder, value: "" }]);
  };

  const handleDelete = (rowKey: string) => {
    commit(rows.filter((r) => r.key !== rowKey));
  };

  const handleEdit = (rowKey: string, field: "name" | "value", next: string) => {
    commit(
      rows.map((r) =>
        r.key === rowKey ? { ...r, [field]: next } : r
      )
    );
  };

  return (
    <div>
      <Table<Row>
        size="small"
        rowKey="key"
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: "暂无,点击下方「添加」按钮新增" }}
        columns={[
          {
            title: "Key",
            dataIndex: "name",
            key: "name",
            render: (_, record) => (
              <Input
                size="small"
                value={record.name}
                placeholder={keyPlaceholder}
                onChange={(e) => handleEdit(record.key, "name", e.target.value)}
              />
            ),
          },
          {
            title: "Value",
            dataIndex: "value",
            key: "value",
            render: (_, record) => (
              <Input
                size="small"
                value={record.value}
                placeholder={valuePlaceholder}
                onChange={(e) => handleEdit(record.key, "value", e.target.value)}
              />
            ),
          },
          {
            title: "",
            key: "action",
            width: 60,
            render: (_, record) => (
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
                onClick={() => handleDelete(record.key)}
              />
            ),
          },
        ]}
      />
      <Space style={{ marginTop: 8 }}>
        <Button
          type="dashed"
          size="small"
          icon={<PlusOutlined />}
          onClick={handleAdd}
        >
          添加
        </Button>
      </Space>
    </div>
  );
}
