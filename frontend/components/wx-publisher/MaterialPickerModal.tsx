// frontend/components/wx-publisher/MaterialPickerModal.tsx
// 2026-06-29 — 草稿编辑器"插入素材"功能补充.
//
// Spec §5.5 只覆盖素材库本身(CRUD + KB 导入),没设计"从素材库插入
// 草稿"的 UX。这个 modal 补这块:列出素材 + 标题搜索 + 来源过滤 + 点
// 击选用。选中后由 page 层调 materialApi.get(id) 拿全文 → append 到
// 当前章节(避免 list 阶段就拉所有 content,带宽浪费)。
"use client";

import { useState, useEffect } from "react";
import {
  Modal,
  Input,
  Select,
  Space,
  Empty,
  Button,
  Skeleton,
} from "antd";
import { SearchOutlined, LinkOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { materialApi } from "@/services/wx-publisher";
import { MaterialList } from "./MaterialList";
import type { WxMaterialListItem } from "@/types/wx-publisher";

interface MaterialPickerModalProps {
  open: boolean;
  onClose: () => void;
  /** 点击素材行的回调 — page 层会拿 item.id 调 materialApi.get 拿全文。 */
  onPick: (item: WxMaterialListItem) => void;
  /** 当前激活的章节标题,显示在 modal 顶部让用户知道会插入哪里。 */
  targetSectionHeading?: string | null;
  /** 「去素材库」链接 — 给空状态时的引导。 */
  onGotoLibrary?: () => void;
}

export function MaterialPickerModal({
  open,
  onClose,
  onPick,
  targetSectionHeading,
  onGotoLibrary,
}: MaterialPickerModalProps) {
  const [search, setSearch] = useState("");
  const [sourceType, setSourceType] = useState<string | undefined>(undefined);
  // debounce search input 300ms — 避免每个 keyup 都触发 query refetch
  const [debouncedSearch, setDebouncedSearch] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  // modal 关闭时清空搜索 + filter — 下次打开是干净状态
  useEffect(() => {
    if (!open) {
      setSearch("");
      setDebouncedSearch("");
      setSourceType(undefined);
    }
  }, [open]);

  const { data, isLoading } = useQuery({
    queryKey: [
      "wx-publisher",
      "materials",
      "picker",
      { q: debouncedSearch, source_type: sourceType ?? null },
    ],
    queryFn: () =>
      materialApi.list({
        page: 1,
        page_size: 50, // picker 一次拉够 50 条,避免分页打断选择节奏
        ...(debouncedSearch ? { search: debouncedSearch } : {}),
        ...(sourceType ? { source_type: sourceType } : {}),
      }),
    enabled: open, // modal 关掉就不拉,省 query
    staleTime: 30_000,
  });

  const items = data?.items ?? [];

  return (
    <Modal
      title={
        <Space>
          <span>从素材库选择</span>
          {targetSectionHeading && (
            <span style={{ fontSize: 12, color: "#888", fontWeight: 400 }}>
              → 插入到「{targetSectionHeading}」
            </span>
          )}
        </Space>
      }
      open={open}
      onCancel={onClose}
      footer={null}
      width={720}
      destroyOnHidden
    >
      <Space style={{ width: "100%", marginBottom: 12 }} size={8}>
        <Input
          allowClear
          placeholder="按标题搜索"
          prefix={<SearchOutlined />}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 280 }}
        />
        <Select
          allowClear
          placeholder="来源"
          style={{ width: 120 }}
          value={sourceType}
          onChange={(v) => setSourceType(v)}
          options={[
            { value: "kb", label: "知识库" },
            { value: "manual", label: "手动" },
            { value: "url", label: "网页剪藏" },
          ]}
        />
        <span style={{ color: "#888", fontSize: 12 }}>
          共 {data?.total ?? 0} 条
        </span>
      </Space>

      {isLoading ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : items.length === 0 ? (
        <Empty
          description={
            debouncedSearch || sourceType
              ? "无匹配素材, 试试清除筛选"
              : "素材库为空"
          }
        >
          {onGotoLibrary && (
            <Button
              type="primary"
              icon={<LinkOutlined />}
              onClick={onGotoLibrary}
            >
              前往素材库新建 →
            </Button>
          )}
        </Empty>
      ) : (
        // 注意: 这里 onPick 不传 onDelete — picker modal 不允许在
        // 选择流程里删素材(防误操作,删素材应去 /materials 页)。
        <div style={{ maxHeight: 480, overflowY: "auto" }}>
          <MaterialList
            items={items}
            loading={false}
            onPick={(item) => {
              onPick(item);
              onClose();
            }}
            pickLabel="插入到章节"
          />
        </div>
      )}
    </Modal>
  );
}

export default MaterialPickerModal;