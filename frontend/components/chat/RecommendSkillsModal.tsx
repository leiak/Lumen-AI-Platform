"use client";

import { Badge, Button, Modal, Tag } from "antd";
import type { SkillRecommendation } from "@/services/chat";

/**
 * M30b-style: 技能推荐确认弹窗 —— 流式发送时由 chatApi.recommendSkills 触发。
 *
 * 用户可以从 AI / 关键词 匹配出的技能里挑最多 5 个,或者直接「不启用」发送。
 */
export function RecommendSkillsModal(props: {
  open: boolean;
  pendingMessage: string;
  recommendedSkills: SkillRecommendation[];
  selectedRecommendIds: number[];
  onToggleRecommend: (skillId: number) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const {
    open,
    pendingMessage,
    recommendedSkills,
    selectedRecommendIds,
    onToggleRecommend,
    onCancel,
    onConfirm,
  } = props;

  return (
    <Modal
      title="推荐技能 — 确认要启用哪些技能?"
      open={open}
      onCancel={onCancel}
      footer={[
        <Button key="cancel" onClick={onCancel}>
          不启用,直接发送
        </Button>,
        <Button
          key="confirm"
          type="primary"
          disabled={selectedRecommendIds.length === 0}
          onClick={onConfirm}
        >
          确认启用 ({selectedRecommendIds.length})
        </Button>,
      ]}
      width={560}
    >
      <div style={{ marginBottom: 12, color: "#666", fontSize: 13 }}>
        根据你的消息「
        {pendingMessage.length > 40
          ? pendingMessage.slice(0, 40) + "..."
          : pendingMessage}
        」,推荐以下技能(最多选5个):
      </div>
      <div style={{ maxHeight: 360, overflowY: "auto" }}>
        {recommendedSkills.map((rec) => {
          const checked = selectedRecommendIds.includes(rec.skill_id);
          return (
            <div
              key={rec.skill_id}
              onClick={() => onToggleRecommend(rec.skill_id)}
              style={{
                padding: "10px 12px",
                marginBottom: 8,
                border: `1px solid ${checked ? "#1890ff" : "#e8e8e8"}`,
                borderRadius: 8,
                cursor: "pointer",
                background: checked ? "#f0f7ff" : "#fff",
                display: "flex",
                alignItems: "flex-start",
                gap: 10,
              }}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => {}}
                style={{ marginTop: 3, flexShrink: 0 }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    marginBottom: 2,
                  }}
                >
                  <span style={{ fontWeight: 600, fontSize: 14 }}>{rec.name}</span>
                  <Badge
                    count={`${Math.round(rec.confidence * 100)}%`}
                    style={{
                      backgroundColor:
                        rec.confidence >= 0.7
                          ? "#52c41a"
                          : rec.confidence >= 0.4
                          ? "#fa8c16"
                          : "#999",
                      fontSize: 10,
                    }}
                    title={`匹配度: ${Math.round(rec.confidence * 100)}%`}
                  />
                  <Tag
                    color={rec.match_type === "llm" ? "purple" : "cyan"}
                    style={{ margin: 0, fontSize: 10 }}
                  >
                    {rec.match_type === "llm" ? "AI 匹配" : "关键词"}
                  </Tag>
                </div>
                {rec.description && (
                  <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>
                    {rec.description}
                  </div>
                )}
                <div style={{ fontSize: 12, color: "#555" }}>
                  <span style={{ color: "#1890ff", fontWeight: 500 }}>理由:</span>
                  {rec.reason}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </Modal>
  );
}