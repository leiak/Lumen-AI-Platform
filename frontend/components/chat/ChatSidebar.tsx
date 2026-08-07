"use client";

import { Button, List, Popconfirm, Tag, Tooltip } from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import type { Conversation } from "@/types/chat";

/**
 * M30b-style: 对话列表 sidebar。无业务逻辑,纯展示。
 *
 * Props:
 * - conversations / currentConv — 数据由 useChatConversations 提供
 * - onSelect / onDelete / onCreate — 行为由 page.tsx 提供
 * - creating / deletingId — loading 状态
 */
export function ChatSidebar(props: {
  conversations: Conversation[];
  currentConv: Conversation | null;
  creating: boolean;
  deletingId: number | null;
  onSelect: (conv: Conversation) => void;
  onDelete: (id: number) => void;
  onCreate: () => void;
}) {
  return (
    <div
      style={{
        width: 300,
        minWidth: 300,
        borderRight: "1px solid #f0f0f0",
        display: "flex",
        flexDirection: "column",
        background: "#fafafa",
      }}
    >
      <div style={{ padding: 16 }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          block
          onClick={props.onCreate}
          loading={props.creating}
        >
          新建对话
        </Button>
      </div>
      <div style={{ flex: 1, overflowY: "auto" }}>
        <List
          dataSource={props.conversations}
          renderItem={(item) => (
            <List.Item
              key={item.id}
              onClick={() => {
                if (props.currentConv?.id !== item.id) {
                  props.onSelect(item);
                }
              }}
              actions={[
                <Popconfirm
                  key="delete"
                  title="确认删除该对话?"
                  okText="删除"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                  onConfirm={(e) => {
                    e?.stopPropagation();
                    props.onDelete(item.id);
                  }}
                  onCancel={(e) => e?.stopPropagation()}
                >
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    loading={props.deletingId === item.id}
                    aria-label="删除"
                    onClick={(e) => e.stopPropagation()}
                  />
                </Popconfirm>,
              ]}
              style={{
                cursor: "pointer",
                background:
                  props.currentConv?.id === item.id ? "#e6f7ff" : "transparent",
                padding: "12px 16px",
              }}
            >
              <List.Item.Meta
                title={
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span
                      style={{
                        flex: 1,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {item.title || "新对话"}
                    </span>
                    {item.agent_id && item.agent_name && (
                      <Tooltip title={`Agent: ${item.agent_name}`}>
                        <Tag color="blue" style={{ marginRight: 0 }}>
                          {item.agent_name.slice(0, 8)}
                        </Tag>
                      </Tooltip>
                    )}
                  </div>
                }
                description={new Date(item.updated_at).toLocaleDateString()}
              />
            </List.Item>
          )}
        />
      </div>
    </div>
  );
}