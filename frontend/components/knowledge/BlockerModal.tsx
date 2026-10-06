"use client";

import { Modal, Button, Typography, List } from "antd";

export interface BlockerModalState {
  visible: boolean;
  message: string;
  agents: { id: number; name: string }[];
  documents: { id: number; filename: string }[];
  truncated: boolean;
}

interface BlockerModalProps {
  state: BlockerModalState;
  onClose: () => void;
}

/**
 * M28 删 KB 失败 blocker modal —— 从 page.tsx 抽出。
 *
 * 后端 422 拦截时弹,展示 blocking_agents / blocking_documents +
 * truncated 警告。toast 3 秒就消失,改持久 modal 让用户能看到 blocker 列表。
 */
export default function BlockerModal({ state, onClose }: BlockerModalProps) {
  return (
    <Modal
      title="无法删除知识库"
      open={state.visible}
      onCancel={onClose}
      footer={[
        <Button key="ok" type="primary" onClick={onClose}>
          知道了
        </Button>,
      ]}
    >
      <p style={{ marginBottom: 16 }}>{state.message}</p>

      {state.agents.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <Typography.Text strong>引用此知识库的 Agent</Typography.Text>
          <List
            size="small"
            style={{ marginTop: 4 }}
            dataSource={state.agents}
            renderItem={(a) => (
              <List.Item>
                <span>
                  {a.name}
                  <Typography.Text type="secondary"> · id={a.id}</Typography.Text>
                </span>
              </List.Item>
            )}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            请到 Agent 详情页的知识库区域取消绑定,或删除该 Agent。
          </Typography.Text>
        </div>
      )}

      {state.documents.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <Typography.Text strong>关联的文档</Typography.Text>
          <List
            size="small"
            style={{ marginTop: 4 }}
            dataSource={state.documents}
            renderItem={(d) => (
              <List.Item>
                <span>
                  {d.filename}
                  <Typography.Text type="secondary">
                    {" "}
                    · id={d.id}
                  </Typography.Text>
                </span>
              </List.Item>
            )}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            请先删除这些文档(回到本页打开「文档列表」可批量删)。
          </Typography.Text>
        </div>
      )}

      {state.truncated && (
        <Typography.Text type="warning" style={{ fontSize: 12 }}>
          列表已截断(后端每次最多返回 10 条),实际 blocker 数量可能更多。
        </Typography.Text>
      )}
    </Modal>
  );
}