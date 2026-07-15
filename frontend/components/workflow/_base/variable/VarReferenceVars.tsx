// frontend/components/workflow/_base/variable/VarReferenceVars.tsx
import { Input, Tag, Empty, Typography } from "antd";
import { useState, useMemo } from "react";
import type { Var } from "./types";

const TYPE_COLOR: Record<string, string> = {
  string: "blue",
  number: "orange",
  boolean: "purple",
  object: "green",
  "array[string]": "cyan",
  "array[number]": "gold",
  "array[object]": "magenta",
  file: "geekblue",
  secret: "red",
  none: "default",
};

export function VarReferenceVars({
  vars,
  onPick,
}: {
  vars: Var[];
  onPick: (v: Var) => void;
}) {
  const [search, setSearch] = useState("");
  const filtered = useMemo(
    () =>
      vars.filter(
        (v) =>
          !search ||
          v.variable.toLowerCase().includes(search.toLowerCase()) ||
          v.nodeTitle.toLowerCase().includes(search.toLowerCase()),
      ),
    [vars, search],
  );
  // Group by nodeId
  const grouped = useMemo(() => {
    const map = new Map<string, { title: string; vars: Var[] }>();
    filtered.forEach((v) => {
      if (!map.has(v.nodeId)) map.set(v.nodeId, { title: v.nodeTitle, vars: [] });
      map.get(v.nodeId)!.vars.push(v);
    });
    return Array.from(map.entries());
  }, [filtered]);

  if (filtered.length === 0) return <Empty description="无可用变量" />;
  return (
    <div>
      <Input.Search
        placeholder="搜索变量"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{ marginBottom: 8 }}
      />
      {grouped.map(([nodeId, { title, vars: vs }]) => (
        <div key={nodeId} style={{ marginBottom: 12 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {title}
          </Typography.Text>
          {vs.map((v) => (
            <div
              key={`${v.nodeId}.${v.variable}`}
              onClick={() => onPick(v)}
              style={{
                cursor: "pointer",
                padding: "4px 8px",
                borderRadius: 4,
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
              data-testid={`var-${v.nodeId}-${v.variable}`}
            >
              <span>{v.variable}</span>
              <Tag color={TYPE_COLOR[v.type] ?? "default"} style={{ marginLeft: "auto" }}>
                {v.type}
              </Tag>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
