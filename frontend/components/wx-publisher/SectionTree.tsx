// frontend/components/wx-publisher/SectionTree.tsx
// M32 — 公众号助手 — 章节树 (左侧列).
//
// Spec §5.3 — 左列: 章节树 + [+ AI 大纲] 按钮 + 每节 [改写][扩写].
// 2026-06-29 — 加 [插入素材] 按钮(无章节时不可点),点击调 onInsertMaterial
// 由 page-level 打开 MaterialPickerModal。
"use client";

import { Button, Space, Empty, Typography, Tooltip } from "antd";
import {
  PlusOutlined,
  EditOutlined,
  ExpandOutlined,
  DeleteOutlined,
  ImportOutlined,
} from "@ant-design/icons";
import type { WxDraftSectionResponse } from "@/types/wx-publisher";

const { Text } = Typography;

interface SectionTreeProps {
  sections: WxDraftSectionResponse[];
  activeId?: number | null;
  onSelect?: (sectionId: number) => void;
  onAddSection?: () => void;
  onAiOutline?: () => void;
  onRewrite?: (sectionId: number) => void;
  onExpand?: (sectionId: number) => void;
  onDelete?: (sectionId: number) => void;
  /** 2026-06-29 新增: 点击「插入素材」按钮,page-level 打开 picker modal。
   *  无激活章节时按钮 disabled。无素材库时此 prop 不传,按钮不渲染。 */
  onInsertMaterial?: () => void;
}

export function SectionTree({
  sections,
  activeId,
  onSelect,
  onAddSection,
  onAiOutline,
  onRewrite,
  onExpand,
  onDelete,
  onInsertMaterial,
}: SectionTreeProps) {
  if (sections.length === 0) {
    return (
      <div style={{ padding: 16 }}>
        <Empty
          description="暂无章节"
          imageStyle={{ height: 60 }}
        >
          <Space direction="vertical" size={4}>
            {onAiOutline && (
              <Button type="primary" icon={<PlusOutlined />} onClick={onAiOutline}>
                AI 大纲生成
              </Button>
            )}
            {onAddSection && (
              <Button onClick={onAddSection}>手动添加章节</Button>
            )}
          </Space>
        </Empty>
      </div>
    );
  }

  // 顶部 toolbar — 加 [插入素材] 按钮(disabled when 没激活章节,
  // 避免点了没目标)
  const noActiveSection = activeId == null;
  return (
    <div style={{ padding: 8 }}>
      <Space style={{ width: "100%", marginBottom: 8 }} direction="vertical" size={4}>
        {onAiOutline && (
          <Button
            block
            type="primary"
            icon={<PlusOutlined />}
            onClick={onAiOutline}
            size="small"
          >
            AI 大纲
          </Button>
        )}
        {onInsertMaterial && (
          <Tooltip
            title={
              noActiveSection
                ? "请先在下方选一个章节"
                : "从素材库选一段插入当前章节"
            }
          >
            <Button
              block
              size="small"
              icon={<ImportOutlined />}
              disabled={noActiveSection}
              onClick={onInsertMaterial}
            >
              插入素材
            </Button>
          </Tooltip>
        )}
        {onAddSection && (
          <Button block size="small" onClick={onAddSection}>
            + 手动添加章节
          </Button>
        )}
      </Space>
      <div style={{ borderTop: "1px solid #f0f0f0", paddingTop: 8 }}>
        {sections.map((section, idx) => {
          const active = activeId === section.id;
          return (
            <div
              key={section.id}
              onClick={() => onSelect?.(section.id)}
              style={{
                padding: "8px 10px",
                borderRadius: 4,
                cursor: "pointer",
                background: active ? "#e6f4ff" : "transparent",
                border: active ? "1px solid #91caff" : "1px solid transparent",
                marginBottom: 4,
              }}
            >
              <div style={{ fontWeight: 500, fontSize: 13, marginBottom: 4 }}>
                <Text type="secondary" style={{ marginRight: 4 }}>
                  {idx + 1}.
                </Text>
                {section.heading ?? "(无标题)"}
              </div>
              <Space size={2} onClick={(e) => e.stopPropagation()}>
                {onRewrite && (
                  <Tooltip title="AI 改写">
                    <Button
                      type="text"
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => onRewrite(section.id)}
                    />
                  </Tooltip>
                )}
                {onExpand && (
                  <Tooltip title="AI 扩写">
                    <Button
                      type="text"
                      size="small"
                      icon={<ExpandOutlined />}
                      onClick={() => onExpand(section.id)}
                    />
                  </Tooltip>
                )}
                {onDelete && (
                  <Tooltip title="删除">
                    <Button
                      type="text"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => onDelete(section.id)}
                    />
                  </Tooltip>
                )}
              </Space>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default SectionTree;