// frontend/components/workflow/nodes/input/VarList.tsx
import { Button, Input, Select, Switch, Table } from "antd";
import { PlusOutlined, DeleteOutlined } from "@ant-design/icons";
import { ALL_VAR_TYPES, InputVariable } from "./types";
import { VarType } from "@/components/workflow/_base/variable/types";

export function VarList({
  value,
  onChange,
}: {
  value: InputVariable[];
  onChange: (v: InputVariable[]) => void;
}) {
  const update = (idx: number, patch: Partial<InputVariable>) => {
    const next = value.map((v, i) => (i === idx ? { ...v, ...patch } : v));
    onChange(next);
  };
  const add = () => onChange([...value, { name: "", type: VarType.string, required: false }]);
  const remove = (idx: number) => onChange(value.filter((_, i) => i !== idx));

  return (
    <div>
      <Table
        size="small"
        pagination={false}
        rowKey={(_, i) => String(i)}
        dataSource={value}
        columns={[
          {
            // 名称 column needs an explicit width: in the 320px-wide left
            // toolbar the 类型/必填/delete columns together ate ~240px,
            // leaving ~56px for the input — placeholder and typed value
            // got visually clipped. 120px fits ~12 chars of "user_query"
            // comfortably and leaves headroom for longer names.
            title: "名称",
            dataIndex: "name",
            width: 120,
            render: (_, _r, i) => (
              <Input
                value={value[i].name}
                placeholder="user_query"
                onChange={(e) => update(i, { name: e.target.value })}
              />
            ),
          },
          {
            title: "类型",
            dataIndex: "type",
            width: 100,
            render: (_, _r, i) => (
              <Select
                value={value[i].type}
                style={{ width: "100%" }}
                onChange={(v) => update(i, { type: v })}
                options={ALL_VAR_TYPES.map((t) => ({ value: t, label: t }))}
              />
            ),
          },
          {
            title: "必填",
            dataIndex: "required",
            width: 50,
            render: (_, _r, i) => (
              <Switch
                checked={value[i].required}
                onChange={(c) => update(i, { required: c })}
              />
            ),
          },
          {
            title: "",
            width: 32,
            render: (_, _r, i) => (
              <Button
                type="text"
                icon={<DeleteOutlined />}
                onClick={() => remove(i)}
              />
            ),
          },
        ]}
      />
      <Button
        type="dashed"
        block
        icon={<PlusOutlined />}
        onClick={add}
        style={{ marginTop: 8 }}
      >
        添加变量
      </Button>
    </div>
  );
}
