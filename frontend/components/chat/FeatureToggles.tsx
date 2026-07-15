"use client";

import { Button, Tooltip, Space } from "antd";
import {
  PaperClipOutlined,
  BulbOutlined,
  GlobalOutlined,
  ThunderboltOutlined,
  FilePptOutlined,
} from "@ant-design/icons";

export interface FeatureTogglesState {
  enableThinking: boolean;
  enableWebSearch: boolean;
  skillIds: number[];   // Skill.id (NOT marketplace_skill_id); the backend uses these to look up InstalledSkill + Skill
}

interface FeatureTogglesProps {
  value: FeatureTogglesState;
  onChange: (next: FeatureTogglesState) => void;
  onPickFile: () => void;
  onOpenSkillPicker: () => void;
  onOpenPptConfig: () => void;
  hasAttachments: boolean;
  disabled?: boolean;
}

/**
 * Three toggle chips placed above the chat input (Qwen-style).
 *
 *  - 📎 附件        — click invokes the parent's file picker; the
 *                      `hasAttachments` flag controls the active highlight
 *  - 🧠 深度思考    — toggles `enableThinking`
 *  - 🌐 联网搜索    — toggles `enableWebSearch`
 */
export function FeatureToggles({
  value,
  onChange,
  onPickFile,
  onOpenSkillPicker,
  onOpenPptConfig,
  hasAttachments,
  disabled,
}: FeatureTogglesProps) {
  return (
    <Space size="small" style={{ marginBottom: 8 }}>
      <Tooltip title="上传附件(临时随消息发送)">
        <Button
          icon={<PaperClipOutlined />}
          size="small"
          type={hasAttachments ? "primary" : "default"}
          onClick={onPickFile}
          disabled={disabled}
        >
          附件
        </Button>
      </Tooltip>

      <Tooltip title="让 AI 用思考链方式回答(输出 <think> 块)">
        <Button
          icon={<BulbOutlined />}
          size="small"
          type={value.enableThinking ? "primary" : "default"}
          onClick={() =>
            onChange({ ...value, enableThinking: !value.enableThinking })
          }
          disabled={disabled}
        >
          深度思考
        </Button>
      </Tooltip>

      <Tooltip title="让 AI 先联网搜索再回答(可能引用 [1] [2] 编号)">
        <Button
          icon={<GlobalOutlined />}
          size="small"
          type={value.enableWebSearch ? "primary" : "default"}
          onClick={() =>
            onChange({ ...value, enableWebSearch: !value.enableWebSearch })
          }
          disabled={disabled}
        >
          联网搜索
        </Button>
      </Tooltip>

      <Tooltip title="为本次对话启用已安装的技能(最多5个)">
        <Button
          icon={<ThunderboltOutlined />}
          size="small"
          type={value.skillIds.length > 0 ? "primary" : "default"}
          onClick={() => onOpenSkillPicker()}
          disabled={disabled}
        >
          技能{value.skillIds.length > 0 ? ` (${value.skillIds.length})` : ""}
        </Button>
      </Tooltip>

      <Tooltip title="根据当前对话生成 PPT">
        <Button
          icon={<FilePptOutlined />}
          size="small"
          onClick={onOpenPptConfig}
          disabled={disabled}
        >
          生成PPT
        </Button>
      </Tooltip>
    </Space>
  );
}
