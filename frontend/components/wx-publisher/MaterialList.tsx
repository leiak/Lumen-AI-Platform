// frontend/components/wx-publisher/MaterialList.tsx
// M32 — 公众号助手 — Material list row.
//
// Spec §5.5 — 每行: 标题(粗) + 内容预览(2 行截断) + 来源 Tag + 标签 Tags +
// 删除按钮. 行级删除 + 标签过滤在 page-level 通过 props 传入.
//
// 2026-06-29 扩展: 新增可选 ``onPick`` 回调,用于"从草稿编辑器插入素材"
// 流程。带 onPick 时,每行最右加 [选用] 链接按钮 — 不带 onPick 时
// 保持原 CRUD 模式。
"use client";

import { List, Tag, Space, Button, Popconfirm } from "antd";
import { DeleteOutlined, ImportOutlined } from "@ant-design/icons";
import type { WxMaterialListItem } from "@/types/wx-publisher";

const SOURCE_TYPE_LABELS: Record<string, string> = {
  kb: "知识库",
  manual: "手动",
  url: "网页剪藏",
};

interface MaterialListProps {
  items: WxMaterialListItem[];
  loading?: boolean;
  onDelete?: (id: number) => void;
  /** 草稿编辑器模式 — 每行显示 [选用] 按钮,点击触发 onPick(material)。
   *  与 onDelete 不互斥,可同时存在(管理后台场景)。 */
  onPick?: (item: WxMaterialListItem) => void;
  /** onPick 按钮文案(默认「选用」)。 */
  pickLabel?: string;
}

export function MaterialList({
  items,
  loading,
  onDelete,
  onPick,
  pickLabel = "选用",
}: MaterialListProps) {
  return (
    <List<WxMaterialListItem>
      loading={loading}
      dataSource={items}
      rowKey="id"
      pagination={false}
      locale={{ emptyText: "暂无素材" }}
      renderItem={(item) => {
        const sourceLabel = SOURCE_TYPE_LABELS[item.source_type] ?? item.source_type;
        // actions 顺序: [选用(可选)] [删除(可选)] — 选用在前更醒目
        const actions = [];
        if (onPick) {
          actions.push(
            <Button
              key="pick"
              type="link"
              size="small"
              icon={<ImportOutlined />}
              onClick={() => onPick(item)}
            >
              {pickLabel}
            </Button>
          );
        }
        if (onDelete) {
          actions.push(
            <Popconfirm
              key="delete"
              title="确认删除该素材?"
              okText="删除"
              cancelText="取消"
              onConfirm={() => onDelete(item.id)}
            >
              <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                删除
              </Button>
            </Popconfirm>
          );
        }
        return (
          <List.Item actions={actions}>
            <List.Item.Meta
              title={
                <Space>
                  <span style={{ fontWeight: 600 }}>{item.title}</span>
                  <Tag color={item.source_type === "kb" ? "blue" : "default"}>
                    {sourceLabel}
                  </Tag>
                  {item.tags?.map((t) => (
                    <Tag key={t} color="cyan">
                      {t}
                    </Tag>
                  ))}
                </Space>
              }
              description={
                <div
                  style={{
                    color: "#666",
                    fontSize: 13,
                    display: "-webkit-box",
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: "vertical",
                    overflow: "hidden",
                  }}
                >
                  {item.content_preview}
                </div>
              }
            />
          </List.Item>
        );
      }}
    />
  );
}

export default MaterialList;