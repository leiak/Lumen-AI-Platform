// frontend/app/dashboard/wx-publisher/drafts/[id]/page.tsx
// M32 — 公众号助手 — 草稿编辑页.
//
// Spec §5.3 — 顶部 Header (返回 + 标题可编辑 + 状态 Tag + 保存/排版/发布)
// + DraftEditor 3 列布局 + AI 改写/扩写 Modal.
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Button,
  Input,
  Tag,
  Space,
  Dropdown,
  App,
  Skeleton,
  Modal,
  Select,
  Alert,
} from "antd";
import {
  ArrowLeftOutlined,
  SaveOutlined,
  LayoutOutlined,
  CloudUploadOutlined,
  ExperimentOutlined,
} from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  draftApi,
  draftAiApi,
  publishApi,
  templateApi,
  accountApi,
  materialApi,
} from "@/services/wx-publisher";
import { DraftEditor } from "@/components/wx-publisher/DraftEditor";
import { AIRewriteModal } from "@/components/wx-publisher/AIRewriteModal";
import { MaterialPickerModal } from "@/components/wx-publisher/MaterialPickerModal";
import { useHtmlPasteHandler } from "@/components/wx-publisher/HtmlPasteHandler";
import type {
  WxDraftDetail,
  WxDraftSectionResponse,
  WxMaterialListItem,
} from "@/types/wx-publisher";

// AIRewriteModal 接受的 action 包括 5 种; 编辑器只触达 'rewrite' | 'expand' 两种.
type EditActionType = "rewrite" | "expand";

const STATUS_COLOR: Record<string, string> = {
  draft: "default",
  rendering: "processing",
  ready: "cyan",
  publishing: "blue",
  published: "success",
  failed: "error",
};

export default function DraftEditPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const { message: toast } = App.useApp();
  const draftId = Number(params?.id);

  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [activeSectionId, setActiveSectionId] = useState<number | null>(null);
  const [aiModal, setAiModal] = useState<{
    open: boolean;
    action: EditActionType;
    sectionId: number | null;
  }>({ open: false, action: "rewrite", sectionId: null });
  const [aiResult, setAiResult] = useState<{
    content: string;
    sectionId: number;
    llm_call_id: string;
  } | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  // 2026-06-29 — 插入素材 modal 控制
  const [materialPickerOpen, setMaterialPickerOpen] = useState(false);

  const { data: draft, isLoading } = useQuery<WxDraftDetail | null>({
    queryKey: ["wx-publisher", "draft", draftId],
    queryFn: async () => {
      try {
        return await draftApi.get(draftId);
      } catch {
        return null;
      }
    },
    enabled: Number.isFinite(draftId),
  });

  // 加载模板列表 — 给 Header 的 template Select 提供选项
  const { data: templatesData } = useQuery({
    queryKey: ["wx-publisher", "templates", { page_size: 100 }],
    queryFn: () => templateApi.list({ page_size: 100 }),
    staleTime: 60_000,
  });
  const templates = templatesData?.items ?? [];
  const currentTemplate = templates.find((t) => t.id === draft?.template_id);

  // 加载公众号账号列表 — Header 的 account Select 用。
  // 只展示启用的账号(is_active=true),停用的不显示。
  // 不传 account_id 过滤:列表里账号数通常 <= 10,一次拉完够了。
  const { data: accountsData, isLoading: accountsLoading } = useQuery({
    queryKey: ["wx-publisher", "accounts", { page_size: 100 }],
    queryFn: () => accountApi.list({ page_size: 100 }),
    staleTime: 60_000,
  });
  const accounts = (accountsData?.items ?? []).filter((a) => a.is_active);
  const currentAccount = accounts.find((a) => a.id === draft?.account_id);
  const noAccounts = !accountsLoading && accounts.length === 0;

  // 同步 server data 到 local state.
  useEffect(() => {
    if (draft) {
      setTitle(draft.title);
      setContent(draft.content_markdown);
      if (!activeSectionId && draft.sections.length > 0) {
        setActiveSectionId(draft.sections[0].id);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft?.id]);

  const handleSave = async () => {
    try {
      await draftApi.update(draftId, { title, content_markdown: content });
      toast.success("已保存");
      qc.invalidateQueries({ queryKey: ["wx-publisher", "draft", draftId] });
    } catch (err: any) {
      toast.error(err?.message || "保存失败");
    }
  };

  const handleRender = async () => {
    if (!draft?.template_id) {
      toast.warning("请先在右上角选择模板");
      return;
    }
    try {
      const res = await draftAiApi.render(draftId, {
        template_id: draft.template_id,
      });
      toast.success("渲染完成");
      qc.setQueryData(["wx-publisher", "draft", draftId], (old: any) => ({
        ...old,
        content_html: res.content_html,
        status: "ready",
      }));
    } catch (err: any) {
      toast.error(err?.message || "渲染失败");
    }
  };

  // 模板切换 — 调 draftApi.update 改 template_id,刷新 query cache
  const handleTemplateChange = async (newTemplateId: number | null) => {
    try {
      const updated = await draftApi.update(draftId, {
        title: draft?.title || title,
        content_markdown: draft?.content_markdown || content,
        template_id: newTemplateId,
      });
      qc.setQueryData(["wx-publisher", "draft", draftId], (old: any) =>
        old ? { ...old, template_id: updated.template_id } : old
      );
      qc.invalidateQueries({ queryKey: ["wx-publisher", "drafts"] });
      toast.success(newTemplateId ? "已绑定模板" : "已取消模板绑定");
    } catch (err: any) {
      toast.error(err?.message || "模板绑定失败");
    }
  };

  // 公众号账号切换 — 同模板切换的模式,只是字段叫 account_id。
  // 取消绑定 (null) 也是合法操作,后端 schema 显式支持 (WxDraftUpdate
  // 注释: "UI explicitly sends nulls for fields the user cleared")。
  const handleAccountChange = async (newAccountId: number | null) => {
    try {
      const updated = await draftApi.update(draftId, {
        title: draft?.title || title,
        content_markdown: draft?.content_markdown || content,
        account_id: newAccountId,
      });
      qc.setQueryData(["wx-publisher", "draft", draftId], (old: any) =>
        old ? { ...old, account_id: updated.account_id } : old
      );
      qc.invalidateQueries({ queryKey: ["wx-publisher", "drafts"] });
      toast.success(newAccountId ? "已绑定公众号" : "已取消公众号绑定");
    } catch (err: any) {
      toast.error(err?.message || "公众号绑定失败");
    }
  };

  const handlePublishNow = async () => {
    if (!draft?.account_id) {
      toast.warning("请先在顶部选择公众号账号,或前往 [公众号账号] 新建");
      return;
    }
    try {
      const record = await publishApi.createPublish({
        draft_id: draftId,
        account_id: draft.account_id,
      });
      toast.success(`已加入发布队列 (#${record.id})`);
    } catch (err: any) {
      toast.error(err?.message || "发布失败");
    }
  };

  const handleAiSubmit = async (
    instruction: string,
    expansion_ratio?: number
  ) => {
    const sectionId = aiModal.sectionId;
    if (!sectionId) return;
    setAiLoading(true);
    try {
      const res =
        aiModal.action === "rewrite"
          ? await draftAiApi.rewrite(draftId, {
              section_id: sectionId,
              instruction,
            })
          : await draftAiApi.expand(draftId, {
              section_id: sectionId,
              instruction,
              ...(expansion_ratio !== undefined
                ? { expansion_ratio }
                : {}),
            } as any);
      setAiResult({
        content: res.new_content_markdown,
        sectionId,
        llm_call_id: res.llm_call_id,
      });
    } catch (err: any) {
      toast.error(err?.message || "AI 调用失败");
      setAiModal((s) => ({ ...s, open: false }));
    } finally {
      setAiLoading(false);
    }
  };

  const handleAiApply = (newContent: string) => {
    if (!aiResult) return;
    qc.setQueryData(["wx-publisher", "draft", draftId], (old: any) => {
      if (!old) return old;
      return {
        ...old,
        sections: old.sections.map((s: WxDraftSectionResponse) =>
          s.id === aiResult.sectionId
            ? { ...s, content_markdown: newContent }
            : s
        ),
      };
    });
    toast.success("已应用到章节");
  };

  // 2026-06-29 — 从素材库插入素材到当前激活章节。
  // picker modal 只给 list_item(200 字预览),这里调 materialApi.get(id) 拿全文。
  // 插入策略:append 到章节 content_markdown 末尾 + 分隔符 (---) — 不替换、不
  // 插中间,避免破坏用户已编辑的结构,后续可在 MD 编辑器里手动调位置。
  const handleInsertMaterial = async (item: WxMaterialListItem) => {
    const targetSectionId = activeSectionId;
    if (!targetSectionId) {
      toast.warning("请先选一个章节");
      return;
    }
    try {
      const full = await materialApi.get(item.id);
      const targetSection =
        draft?.sections.find((s) => s.id === targetSectionId);
      if (!targetSection) {
        toast.error("找不到目标章节");
        return;
      }
      // 拼接:已有内容 + 分隔 + 素材标题(heading)+ 素材正文。
      // 用 heading 让用户在 MD 编辑器里立刻看出"这段是素材插入的",
      // 同时给 publish 后渲染 HTML 一个清晰的段落锚点。
      const separator = "\n\n---\n\n";
      const headingLine = full.title ? `> **${full.title}**\n` : "";
      const newContent =
        (targetSection.content_markdown || "") +
        separator +
        headingLine +
        full.content;

      // 同步 query cache + 本地 content state
      qc.setQueryData(["wx-publisher", "draft", draftId], (old: any) => {
        if (!old) return old;
        return {
          ...old,
          sections: old.sections.map((s: WxDraftSectionResponse) =>
            s.id === targetSectionId
              ? { ...s, content_markdown: newContent }
              : s
          ),
        };
      });
      setContent(newContent);
      toast.success(`已插入素材: ${item.title}`);
    } catch (err: any) {
      toast.error(err?.message || "插入素材失败");
    }
  };

  // M32.1:粘贴飞书/网页 HTML → 自动转 MD → 替换当前 content
  // 后端把转换后的 MD append 到 content_markdown 末尾(全文返回),
  // 这里直接用全文替换 content state 并同步到 query cache。
  // 注意:这个 useCallback 必须在 activeSection 计算之前 — 我们用
  // useMemo 在 early-return 之前计算 activeSection(基于 draft 可选链)。
  const activeSection = useMemo(
    () =>
      draft
        ? draft.sections.find((s) => s.id === activeSectionId) ?? null
        : null,
    [draft, activeSectionId]
  );
  const handlePasteConverted = useCallback(
    (fullMarkdown: string) => {
      setContent(fullMarkdown);
      qc.setQueryData(["wx-publisher", "draft", draftId], (old: any) => {
        if (!old) return old;
        return {
          ...old,
          content_markdown: fullMarkdown,
          // 如果有 activeSection,同步它的 content_markdown
          sections: activeSection
            ? old.sections.map((s: WxDraftSectionResponse) =>
                s.id === activeSection.id
                  ? { ...s, content_markdown: fullMarkdown }
                  : s
              )
            : old.sections,
        };
      });
    },
    [qc, draftId, activeSection]
  );
  const handlePasteHtml = useHtmlPasteHandler({
    draftId,
    onConverted: handlePasteConverted,
  });

  if (isLoading) {
    return (
      <div style={{ padding: 24 }}>
        <Skeleton active />
      </div>
    );
  }

  if (!draft) {
    return (
      <div style={{ padding: 24 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => router.back()}>
          返回
        </Button>
        <p style={{ marginTop: 16 }}>草稿不存在或已删除.</p>
      </div>
    );
  }

  return (
    <div style={{ padding: 24 }}>
      {/* Header */}
      <Space style={{ marginBottom: 16, width: "100%" }} size={12} wrap>
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() => router.push("/dashboard/wx-publisher/drafts")}
        >
          返回
        </Button>
        <Input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          style={{ width: 360, fontWeight: 600 }}
          placeholder="标题"
        />
        <Tag color={STATUS_COLOR[draft.status] ?? "default"}>{draft.status}</Tag>
        {/* 公众号账号选择器 — 修复「发布时提示绑定,但找不到入口」问题。
            选项按 is_active 过滤(只显示启用的),allowClear 允许解绑(null 走 PATCH)。 */}
        <Select
          allowClear
          loading={accountsLoading}
          placeholder="选择公众号账号"
          value={draft.account_id ?? undefined}
          onChange={(v) => handleAccountChange(v ?? null)}
          style={{ minWidth: 220 }}
          popupMatchSelectWidth={false}
          options={accounts.map((a) => ({
            value: a.id,
            label: (
              <span>
                <Tag
                  color={
                    a.account_type === "service"
                      ? "gold"
                      : a.account_type === "enterprise"
                      ? "purple"
                      : "blue"
                  }
                  style={{ marginRight: 6 }}
                >
                  {a.account_type}
                </Tag>
                {a.name}
                {a.is_mock && (
                  <Tag color="orange" style={{ marginLeft: 6 }}>
                    Mock
                  </Tag>
                )}
              </span>
            ),
          }))}
        />
        {/* 模板选择器 — M32.1 修复「应用模板」找不到入口问题 */}
        <Select
          allowClear
          loading={!templatesData}
          placeholder="选择模板"
          value={draft.template_id ?? undefined}
          onChange={(v) => handleTemplateChange(v ?? null)}
          style={{ minWidth: 200 }}
          popupMatchSelectWidth={false}
          options={templates.map((t) => ({
            value: t.id,
            label: (
              <span>
                <Tag color="blue" style={{ marginRight: 6 }}>
                  {t.category}
                </Tag>
                {t.name}
              </span>
            ),
          }))}
        />
        <div style={{ flex: 1 }} />
        {/* 当前选中的账号 + mock 模式提示 — 已绑定时,在发布按钮旁边给一个 inline hint,
            避免用户在 Mock 模式下误发真实账号。 */}
        {currentAccount && currentAccount.is_mock && (
          <Tag color="orange" icon={<ExperimentOutlined />}>
            Mock 模式(不会真实发送)
          </Tag>
        )}
        <Button icon={<SaveOutlined />} onClick={handleSave}>
          保存草稿
        </Button>
        <Button icon={<LayoutOutlined />} onClick={handleRender}>
          应用模板
        </Button>
        <Dropdown
          menu={{
            items: [
              {
                key: "now",
                label: "立即发布",
                icon: <CloudUploadOutlined />,
                onClick: handlePublishNow,
              },
              {
                key: "save-only",
                label: "仅存为微信草稿",
                onClick: handlePublishNow,
              },
            ],
          }}
        >
          <Button type="primary" icon={<CloudUploadOutlined />}>
            发布
          </Button>
        </Dropdown>
      </Space>

      <DraftEditor
        sections={draft.sections}
        activeSectionId={activeSectionId}
        content={
          activeSection
            ? activeSection.content_markdown
            : content
        }
        renderedHtml={draft.content_html}
        status={draft.status}
        onSelectSection={(id) => {
          setActiveSectionId(id);
          const s = draft.sections.find((sec) => sec.id === id);
          if (s) setContent(s.content_markdown);
        }}
        onContentChange={(v) => {
          setContent(v);
          if (activeSection) {
            qc.setQueryData(["wx-publisher", "draft", draftId], (old: any) => {
              if (!old) return old;
              return {
                ...old,
                sections: old.sections.map((s: WxDraftSectionResponse) =>
                  s.id === activeSection.id
                    ? { ...s, content_markdown: v }
                    : s
                ),
              };
            });
          }
        }}
        onRewrite={(id) =>
          setAiModal({ open: true, action: "rewrite", sectionId: id })
        }
        onExpand={(id) =>
          setAiModal({ open: true, action: "expand", sectionId: id })
        }
        onInsertMaterial={() => setMaterialPickerOpen(true)}
        onPasteHtml={handlePasteHtml}
      />

      {/* 空状态 Alert — 没有可用公众号账号时,在底部给一个不打扰的引导。
          放在编辑器下方而不是盖在 Header 上,让用户先看到编辑器形态;有 Alert
          之后要点发布才会被这条挡住。 */}
      {noAccounts && (
        <Alert
          style={{ marginTop: 16 }}
          type="warning"
          showIcon
          message="还没有可用的公众号账号"
          description={
            <span>
              发布前需要先新建一个公众号账号(AppID + AppSecret)。
              <Button
                type="link"
                size="small"
                style={{ paddingLeft: 8 }}
                onClick={() => router.push("/dashboard/wx-publisher/accounts")}
              >
                前往公众号账号页新建 →
              </Button>
            </span>
          }
        />
      )}

      <AIRewriteModal
        open={aiModal.open}
        action={aiModal.action}
        section={activeSection}
        newContent={aiResult?.sectionId === aiModal.sectionId ? aiResult.content : null}
        loading={aiLoading}
        onCancel={() => {
          setAiModal({ open: false, action: "rewrite" as EditActionType, sectionId: null });
          setAiResult(null);
        }}
        onSubmit={handleAiSubmit}
        onApply={handleAiApply}
      />

      {/* 2026-06-29 — 插入素材 modal */}
      <MaterialPickerModal
        open={materialPickerOpen}
        onClose={() => setMaterialPickerOpen(false)}
        onPick={handleInsertMaterial}
        targetSectionHeading={activeSection?.heading ?? null}
        onGotoLibrary={() => {
          setMaterialPickerOpen(false);
          router.push("/dashboard/wx-publisher/materials");
        }}
      />
    </div>
  );
}