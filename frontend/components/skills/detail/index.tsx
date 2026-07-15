"use client";
import { MarketplaceSkill } from "@/services/skills";
import { PromptDetail } from "./PromptDetail";
import { ScriptDetail } from "./ScriptDetail";
import { HttpDetail } from "./HttpDetail";
import { KnowledgeRetrievalDetail } from "./KnowledgeRetrievalDetail";
import { ToolDetail } from "./ToolDetail";

export function SkillDetailContent({ skill }: { skill: MarketplaceSkill }) {
  // Backward compat: missing/unknown type → prompt (per M16 §3.9)
  const t = skill.type ?? "prompt";
  switch (t) {
    case "script":
      return <ScriptDetail skill={skill} />;
    case "http":
      return <HttpDetail skill={skill} />;
    case "knowledge_retrieval":
      return <KnowledgeRetrievalDetail skill={skill} />;
    case "tool":
      return <ToolDetail skill={skill} />;
    case "prompt":
    default:
      return <PromptDetail skill={skill} />;
  }
}
