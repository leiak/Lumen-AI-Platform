"use client";
import { Tag } from "antd";

// Map skill type → display label + AntD color
const TYPE_CONFIG: Record<string, { label: string; color: string }> = {
  prompt: { label: "提示词", color: "blue" },
  script: { label: "脚本", color: "green" },
  http: { label: "API", color: "orange" },
  knowledge_retrieval: { label: "知识库", color: "purple" },
  tool: { label: "工具", color: "cyan" },
  workflow: { label: "工作流", color: "default" },
  composite: { label: "组合", color: "gold" },
};

export function SkillTypeTag({ type, fallback = true }: { type?: string; fallback?: boolean }) {
  const config = (type && TYPE_CONFIG[type]) || (fallback ? TYPE_CONFIG.prompt : null);
  if (!config) return null;
  return <Tag color={config.color}>{config.label}</Tag>;
}

export function skillTypeLabel(type?: string): string {
  if (!type) return "提示词";
  return TYPE_CONFIG[type]?.label || "提示词";
}
