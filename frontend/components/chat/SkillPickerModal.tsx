"use client";

import { Modal, Select } from "antd";

/**
 * M30b-style: 已装技能多选弹窗。纯展示。
 *
 * 选项 prop `installedSkills` 是 [{value, label, category}] 形态 —— 由
 * useChatSkills 提供。`draftSkillIds` 双向绑定,`onChangeDraft` 上交 page。
 */
export function SkillPickerModal(props: {
  open: boolean;
  installedSkills: { value: number; label: string; category: string }[];
  draftSkillIds: number[];
  onChangeDraft: (ids: number[]) => void;
  onOk: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal
      title="选择本次对话要启用的技能"
      open={props.open}
      onCancel={props.onCancel}
      onOk={props.onOk}
      okText="确定"
      cancelText="取消"
      width={520}
    >
      <Select
        mode="multiple"
        allowClear
        placeholder="选择已装技能(最多5个)"
        value={props.draftSkillIds}
        onChange={(v) => props.onChangeDraft(v as number[])}
        options={props.installedSkills}
        optionFilterProp="label"
        style={{ width: "100%" }}
        maxTagCount={5}
      />
      {props.draftSkillIds.length >= 5 && (
        <div style={{ marginTop: 8, color: "#fa8c16" }}>已达 5 个上限。</div>
      )}
    </Modal>
  );
}