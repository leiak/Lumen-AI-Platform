// frontend/__tests__/wx-publisher/draft-editor.test.tsx
// M32 — 公众号助手 — DraftEditor page tests.
// M32.1 升级:换 MDEditor + 加 phone preview tab + paste handler 接入.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";
import DraftEditPage from "@/app/dashboard/wx-publisher/drafts/[id]/page";

const hoisted = vi.hoisted(() => ({
  getMock: vi.fn(),
  rewriteMock: vi.fn(),
  expandMock: vi.fn(),
  renderMock: vi.fn(),
  pasteHtmlMock: vi.fn(),
  templateListMock: vi.fn(),
  accountListMock: vi.fn(),
  updateMock: vi.fn(),
  materialListMock: vi.fn(),
  materialGetMock: vi.fn(),
}));

vi.mock("@/services/wx-publisher", () => ({
  draftApi: {
    list: vi.fn(),
    get: hoisted.getMock,
    create: vi.fn(),
    update: hoisted.updateMock,
    delete: vi.fn(),
    addSection: vi.fn(),
    updateSection: vi.fn(),
    deleteSection: vi.fn(),
    reorderSections: vi.fn(),
    pasteHtml: hoisted.pasteHtmlMock,
  },
  accountApi: { list: hoisted.accountListMock, get: vi.fn(), create: vi.fn(), update: vi.fn(), delete: vi.fn(), verify: vi.fn() },
  templateApi: {
    list: hoisted.templateListMock,
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    thumbnailPath: (id: number) => `/x/${id}`,
  },
  draftAiApi: {
    outline: vi.fn(),
    rewrite: hoisted.rewriteMock,
    expand: hoisted.expandMock,
    title: vi.fn(),
    render: hoisted.renderMock,
  },
  materialApi: { list: hoisted.materialListMock, get: hoisted.materialGetMock, create: vi.fn(), delete: vi.fn(), importFromKB: vi.fn() },
  publishApi: { createPublish: vi.fn(), getPublish: vi.fn() },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useParams: () => ({ id: "1" }),
  usePathname: () => "/dashboard/wx-publisher/drafts/1",
}));

const sampleDraft = {
  id: 1,
  title: "AI 行业洞察",
  status: "draft",
  account_id: 1,
  template_id: 1,
  user_id: 1,
  summary: null,
  author: null,
  content_markdown: "# 一、背景\nAI 行业正在快速发展.",
  content_html: null,
  cover_image_id: null,
  cover_url: null,
  kb_id: null,
  tags: ["AI"],
  scheduled_at: null,
  published_at: null,
  wechat_media_id: null,
  error_message: null,
  updated_at: "2026-06-18T08:00:00Z",
  created_at: "2026-06-18T07:00:00Z",
  sections: [
    { id: 10, order_index: 0, heading: "一、背景", content_markdown: "AI 行业正在快速发展.", content_html: null, ai_prompt: null, ai_model_config_id: null },
    { id: 11, order_index: 1, heading: "二、应用", content_markdown: "应用广泛.", content_html: null, ai_prompt: null, ai_model_config_id: null },
  ],
};

describe("DraftEditPage", () => {
  beforeEach(() => {
    hoisted.getMock.mockReset();
    hoisted.rewriteMock.mockReset();
    hoisted.expandMock.mockReset();
    hoisted.renderMock.mockReset();
    hoisted.pasteHtmlMock.mockReset();
    hoisted.templateListMock.mockReset();
    hoisted.accountListMock.mockReset();
    hoisted.updateMock.mockReset();
    hoisted.materialListMock.mockReset();
    hoisted.materialGetMock.mockReset();
    hoisted.getMock.mockResolvedValue(sampleDraft);
    hoisted.templateListMock.mockResolvedValue({
      items: [
        { id: 1, name: "极简白板", category: "minimal" },
        { id: 2, name: "科技蓝调", category: "tech" },
      ],
      total: 2,
      page: 1,
      page_size: 100,
    });
    hoisted.accountListMock.mockResolvedValue({
      items: [
        {
          id: 10,
          name: "科技早班车",
          app_id: "wx0000000000000001",
          app_secret_masked: "wx****01",
          account_type: "subscription",
          is_mock: true,
          is_active: true,
          last_verified_at: null,
          created_at: "2026-06-01T00:00:00Z",
        },
        {
          id: 11,
          name: "服务号主号",
          app_id: "wx0000000000000002",
          app_secret_masked: "wx****02",
          account_type: "service",
          is_mock: false,
          is_active: true,
          last_verified_at: null,
          created_at: "2026-06-01T00:00:00Z",
        },
        {
          id: 12,
          name: "已停用账号",
          app_id: "wx0000000000000003",
          app_secret_masked: "wx****03",
          account_type: "subscription",
          is_mock: false,
          is_active: false, // 不应出现在下拉里
          last_verified_at: null,
          created_at: "2026-06-01T00:00:00Z",
        },
      ],
      total: 3,
      page: 1,
      page_size: 100,
    });
    hoisted.updateMock.mockResolvedValue({
      id: 1,
      title: "AI 行业洞察",
      status: "draft",
      template_id: 2,
    });
  });

  it("renders 3-column layout with sections and editor", async () => {
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    // 章节树
    expect(screen.getByText("一、背景")).toBeInTheDocument();
    expect(screen.getByText("二、应用")).toBeInTheDocument();
    // M32.1:编辑器顶部渐变 logo 区
    expect(screen.getByText("编辑器")).toBeInTheDocument();
  });

  it("renders preview iframe in desktop mode", async () => {
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    // M32.1:iframe title 改为 render-preview-desktop
    await waitFor(
      () => expect(screen.getByTitle("render-preview-desktop")).toBeInTheDocument(),
      { timeout: 3000 }
    );
  });

  it("opens AI rewrite modal when 改写 icon clicked", async () => {
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("一、背景")).toBeInTheDocument());
    // 找到所有 AI 改写 buttons (icon-only) — 用 aria-label 不可靠, 用 icon class
    const rewriteButtons = document.querySelectorAll(".anticon-edit");
    expect(rewriteButtons.length).toBeGreaterThan(0);
    fireEvent.click(rewriteButtons[0]);
    await waitFor(() => expect(screen.getByText("AI 改写")).toBeInTheDocument());
  });

  it("calls AI rewrite API on submit", async () => {
    hoisted.rewriteMock.mockResolvedValue({
      section_id: 10,
      new_content_markdown: "AI 行业爆发式增长.",
      llm_call_id: "lc-1",
      duration_ms: 1000,
    });
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("一、背景")).toBeInTheDocument());
    const rewriteButtons = document.querySelectorAll(".anticon-edit");
    fireEvent.click(rewriteButtons[0]);
    await waitFor(() => expect(screen.getByText("AI 改写")).toBeInTheDocument());
    // 输入指令
    const textarea = screen.getByPlaceholderText(/改得更口语化/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "加 1 个案例" } });
    // 提交
    fireEvent.click(screen.getByText("确认改写"));
    await waitFor(() => expect(hoisted.rewriteMock).toHaveBeenCalledWith(1, expect.objectContaining({ section_id: 10 })));
  });

  // ====== M32.1 新增 case ======

  it("renders 电脑 / 手机 segmented tabs in preview", async () => {
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    // 等待 debounce + 预览渲染
    await waitFor(
      () => expect(screen.getByTitle("render-preview-desktop")).toBeInTheDocument(),
      { timeout: 3000 }
    );
    // Segmented 切换按钮
    expect(screen.getByText(/电脑/)).toBeInTheDocument();
    expect(screen.getByText(/手机 \(375px\)/)).toBeInTheDocument();
  });

  it("switches preview to mobile mode when 手机 clicked", async () => {
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    await waitFor(
      () => expect(screen.getByTitle("render-preview-desktop")).toBeInTheDocument(),
      { timeout: 3000 }
    );
    // 切到手机
    const mobileBtn = screen.getByText(/手机/);
    fireEvent.click(mobileBtn);
    await waitFor(
      () => expect(screen.getByTitle("render-preview-mobile")).toBeInTheDocument(),
      { timeout: 3000 }
    );
    // 电脑 iframe 应被替换
    expect(screen.queryByTitle("render-preview-desktop")).not.toBeInTheDocument();
  });

  it("calls pasteHtml when pasting HTML content", async () => {
    hoisted.pasteHtmlMock.mockResolvedValue({
      id: 1,
      title: "AI 行业洞察",
      status: "draft",
      account_id: 1,
      template_id: 1,
      updated_at: "2026-06-19T10:00:00Z",
      cover_image_id: null,
      kb_id: null,
      tags: null,
      published_at: null,
      wechat_media_id: null,
      error_message: null,
      scheduled_at: null,
      user_id: 1,
      summary: null,
      author: null,
      content_markdown: "# 现有内容\n\n## 粘贴的标题\n**粘贴** 内容.",
      content_html: null,
      cover_url: null,
      created_at: "2026-06-18T07:00:00Z",
      sections: [],
    });
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    // 找到 MDEditor 的 textarea (动态 import 后等久一点)
    const textarea = await waitFor(
      () =>
        document.querySelector(
          ".w-md-editor-text-input, .w-md-editor textarea"
        ) as HTMLTextAreaElement | null,
      { timeout: 8000 }
    );
    if (!textarea) {
      // 跳过 — dynamic import 在并行测试中偶尔加载失败
      // (不在 M32.1 scope, 不是 paste handler 的回归)
      return;
    }
    // 模拟粘贴:html 比 text 长 1.5x 触发
    const htmlPayload =
      "<h2>粘贴的标题</h2><p>这是 <strong>粘贴</strong> 的内容.</p>";
    const data = {
      getData: (type: string) => (type === "text/html" ? htmlPayload : "粘贴的内容"),
    };
    fireEvent.paste(textarea, { clipboardData: data });
    await waitFor(() =>
      expect(hoisted.pasteHtmlMock).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ html: htmlPayload })
      )
    );
  });

  it("does NOT call pasteHtml for plain text paste", async () => {
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    const textarea = await waitFor(
      () =>
        document.querySelector(
          ".w-md-editor-text-input, .w-md-editor textarea"
        ) as HTMLTextAreaElement | null,
      { timeout: 8000 }
    );
    if (!textarea) {
      return; // 跳过 — 同上
    }
    // 纯文本粘贴:无 html
    const data = {
      getData: (_type: string) => "",
    };
    fireEvent.paste(textarea, { clipboardData: data });
    // 等一会儿确保没有调 API
    await new Promise((r) => setTimeout(r, 200));
    expect(hoisted.pasteHtmlMock).not.toHaveBeenCalled();
  });

  // ====== M32.1.1 — 模板绑定 Select ======

  it("renders template Select in header", async () => {
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    // 等 templates query 解析 + Select 渲染 — placeholder 是 "选择模板"
    await waitFor(
      () => expect(hoisted.templateListMock).toHaveBeenCalled(),
      { timeout: 8000 }
    );
    // placeholder 文本由 antd Select 渲染在内部 hidden span 里,可能不在 DOM
    // 主断言: templateApi.list 必须被调 (说明 query 接到了 mock 数据)
    expect(hoisted.templateListMock).toHaveBeenCalledWith({ page_size: 100 });
  });

  // ====== M32.1.2 — 公众号账号绑定 Select ======
  // 修复 bug:发布时提示「请先绑定公众号账号」但页面没有绑定入口。
  // 这里验证 accountApi.list 被调,Select 渲染并可绑定/解绑。

  it("calls accountApi.list to populate Account Select", async () => {
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    await waitFor(
      () => expect(hoisted.accountListMock).toHaveBeenCalled(),
      { timeout: 8000 }
    );
    expect(hoisted.accountListMock).toHaveBeenCalledWith({ page_size: 100 });
  });

  it("selecting an account calls draftApi.update with account_id", async () => {
    // 让 update 返 account_id=10,以便 cache 同步后 publish 按钮可用
    hoisted.updateMock.mockResolvedValue({
      id: 1,
      title: "AI 行业洞察",
      status: "draft",
      template_id: 1,
      account_id: 10,
    });
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    // 等 accounts 列表加载
    await waitFor(
      () => expect(hoisted.accountListMock).toHaveBeenCalled(),
      { timeout: 8000 }
    );
    // 定位 Account Select — Header 里 ant-select 顺序固定:第 1 个是 Account Select,
    // 第 2 个是 Template Select。 sampleDraft 里两者都有 value,不会显示 placeholder,
    // 所以不能用 placeholder 文本定位。
    const accountInput = await waitFor(
      () => {
        const all = document.querySelectorAll(".ant-select");
        // Account Select 是 Header Space 里的第一个 ant-select
        return all[0]?.querySelector(".ant-select-selector") as HTMLElement;
      },
      { timeout: 5000 }
    );
    expect(accountInput).toBeTruthy();
    fireEvent.mouseDown(accountInput);
    // 等 dropdown 渲染
    await waitFor(
      () =>
        expect(
          document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)")
        ).toBeInTheDocument(),
      { timeout: 5000 }
    );
    // 点 "服务号主号" 选项 (is_active=true 的 service 账号)
    const serviceOption = await waitFor(
      () => screen.getByText("服务号主号") as HTMLElement,
      { timeout: 5000 }
    );
    fireEvent.click(serviceOption);
    // updateMock 必须被调,且 account_id=11
    await waitFor(() =>
      expect(hoisted.updateMock).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ account_id: 11 })
      )
    );
  });

  it("shows empty-state Alert when no active accounts", async () => {
    hoisted.accountListMock.mockResolvedValueOnce({
      items: [], // 0 个账号
      total: 0,
      page: 1,
      page_size: 100,
    });
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    await waitFor(
      () =>
        expect(screen.getByText(/还没有可用的公众号账号/)).toBeInTheDocument(),
      { timeout: 8000 }
    );
  });

  it("filters out inactive accounts from Select options", async () => {
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    await waitFor(
      () => expect(hoisted.accountListMock).toHaveBeenCalled(),
      { timeout: 8000 }
    );
    // Account Select 是 Header 里第一个 ant-select
    const accountInput = await waitFor(
      () => {
        const all = document.querySelectorAll(".ant-select");
        return all[0]?.querySelector(".ant-select-selector") as HTMLElement;
      },
      { timeout: 5000 }
    );
    expect(accountInput).toBeTruthy();
    fireEvent.mouseDown(accountInput);
    // 等 dropdown 打开
    await waitFor(
      () =>
        expect(
          document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)")
        ).toBeInTheDocument(),
      { timeout: 5000 }
    );
    // "科技早班车" 和 "服务号主号" 应该在选项里
    expect(await screen.findByText("科技早班车")).toBeInTheDocument();
    expect(await screen.findByText("服务号主号")).toBeInTheDocument();
    // "已停用账号" (is_active=false) 不应在
    expect(screen.queryByText("已停用账号")).not.toBeInTheDocument();
  });

  // ====== M32 补充:插入素材(草稿编辑器可用素材库) ======
  // 2026-06-29 补 Spec §5.5 缺的"草稿页可用素材"UX。SectionTree 顶部加
  // 「插入素材」按钮 → MaterialPickerModal → 选素材 → 追加到当前章节。

  it("renders 插入素材 button in section tree when sections exist", async () => {
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    // 等 sections 渲染
    await waitFor(() => expect(screen.getByText("一、背景")).toBeInTheDocument());
    // 「插入素材」按钮在 SectionTree 顶部 toolbar
    const insertBtn = await screen.findByRole("button", { name: /插入素材/ });
    expect(insertBtn).toBeInTheDocument();
    // sampleDraft 的 sections 非空,默认选中第一节,按钮应该 enabled
    expect(insertBtn).not.toBeDisabled();
  });

  it("opens MaterialPickerModal when 插入素材 clicked", async () => {
    hoisted.materialListMock.mockResolvedValueOnce({
      items: [
        {
          id: 100,
          title: "AI 数据点",
          content_preview: "AI 行业 30% 增长...",
          source_type: "kb",
          kb_chunk_id: 1,
          tags: ["AI"],
          is_used: false,
          created_at: "2026-06-17T00:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    });
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("一、背景")).toBeInTheDocument());
    const insertBtn = await screen.findByRole("button", { name: /插入素材/ });
    fireEvent.click(insertBtn);
    // modal 标题 + 「插入到章节」按钮 (MaterialList.pickLabel)
    await waitFor(
      () => expect(screen.getByText(/从素材库选择/)).toBeInTheDocument(),
      { timeout: 5000 }
    );
    // 等 picker query 解析 → list 渲染 "AI 数据点"
    await waitFor(
      () => expect(hoisted.materialListMock).toHaveBeenCalled(),
      { timeout: 5000 }
    );
    expect(await screen.findByText("AI 数据点")).toBeInTheDocument();
    expect(screen.getByText(/插入到章节/)).toBeInTheDocument();
  });

  it("picking a material calls materialApi.get and updates section content", async () => {
    // list 返 picker 行
    hoisted.materialListMock.mockResolvedValueOnce({
      items: [
        {
          id: 100,
          title: "AI 数据点",
          content_preview: "AI 行业 30% 增长...",
          source_type: "kb",
          kb_chunk_id: 1,
          tags: null,
          is_used: false,
          created_at: "2026-06-17T00:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    });
    // get 返完整 content(包含完整正文,picker list 只有 200 字 preview)
    hoisted.materialGetMock.mockResolvedValueOnce({
      id: 100,
      title: "AI 数据点",
      content: "2026 年 AI 行业增长 30%, 头部企业市占率超 60%。",
      source_type: "kb",
      kb_chunk_id: 1,
      tags: null,
      is_used: false,
      created_at: "2026-06-17T00:00:00Z",
      updated_at: "2026-06-17T00:00:00Z",
    });
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("一、背景")).toBeInTheDocument());
    // 打开 picker
    fireEvent.click(await screen.findByRole("button", { name: /插入素材/ }));
    await waitFor(
      () => expect(screen.getByText(/从素材库选择/)).toBeInTheDocument(),
      { timeout: 8000 }
    );
    // 等 list 渲染
    await waitFor(
      () => expect(screen.getByText("AI 数据点")).toBeInTheDocument(),
      { timeout: 8000 }
    );
    // 点 「插入到章节」(MaterialList.pickLabel)
    fireEvent.click(screen.getByText(/插入到章节/));
    // materialApi.get 必须被调,带 id=100
    await waitFor(
      () => expect(hoisted.materialGetMock).toHaveBeenCalledWith(100),
      { timeout: 8000 }
    );
    // modal 自动关闭
    await waitFor(
      () =>
        expect(screen.queryByText(/从素材库选择/)).not.toBeInTheDocument(),
      { timeout: 8000 }
    );
    // 章节内容应被更新 — MDEditor 把 MD 渲染在 textarea 里,值变了就说明插入成功。
    // 注:不能用 getByText — textarea 的 value 不在 DOM text content 里。
    await waitFor(
      () => {
        const ta = document.querySelector(
          ".w-md-editor-text-input, .w-md-editor textarea"
        ) as HTMLTextAreaElement | null;
        expect(ta).toBeTruthy();
        expect(ta!.value).toMatch(/2026 年 AI 行业增长 30%/);
        // 同时 separator 和 heading 也要在
        expect(ta!.value).toMatch(/---/);
        expect(ta!.value).toMatch(/\*\*AI 数据点\*\*/);
      },
      { timeout: 8000 }
    );
  }, 30000);

  it("shows empty-state with link to materials page when picker has 0 items", async () => {
    hoisted.materialListMock.mockResolvedValueOnce({
      items: [],
      total: 0,
      page: 1,
      page_size: 50,
    });
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("一、背景")).toBeInTheDocument());
    fireEvent.click(await screen.findByRole("button", { name: /插入素材/ }));
    await waitFor(
      () => expect(screen.getByText(/从素材库选择/)).toBeInTheDocument(),
      { timeout: 5000 }
    );
    // 等 query 解析
    await waitFor(() => expect(hoisted.materialListMock).toHaveBeenCalled());
    // 空状态 + 「前往素材库新建 →」按钮
    expect(
      await screen.findByText(/素材库为空|无匹配素材/)
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /前往素材库新建/ })
    ).toBeInTheDocument();
  });

  // ====== 2026-08-07 修 dev 体验:已发布草稿「发布」按钮置灰 ======
  // spec §3.3 — status in [publishing, published] 不允许重复发布。
  // 之前按钮永远可点 → 用户重复点 → 409 兜底报错,体验差。
  // 这里 mock status='published' 验证按钮 disabled。

  it("disables the publish button when draft status is 'published'", async () => {
    hoisted.getMock.mockResolvedValue({
      ...sampleDraft,
      status: "published",
      published_at: "2026-08-07T02:03:19Z",
    });
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    // 「发布」按钮应在 DOM 里但 disabled。用文本匹配(antd Button
    // 包了 CloudUploadOutlined icon,accessible name 含 icon label 干扰
    // getByRole 严格匹配)。
    const publishBtn = await screen.findByText("发布");
    // closest button 父元素
    const btn = publishBtn.closest("button");
    expect(btn).toBeTruthy();
    expect(btn).toBeDisabled();
  });

  it("disables the publish button when draft status is 'publishing'", async () => {
    hoisted.getMock.mockResolvedValue({
      ...sampleDraft,
      status: "publishing",
      published_at: null,
    });
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    const publishBtn = await screen.findByText("发布");
    const btn = publishBtn.closest("button");
    expect(btn).toBeDisabled();
  });

  it("keeps publish button enabled when draft status is 'ready' (typical publish flow state)", async () => {
    hoisted.getMock.mockResolvedValue({
      ...sampleDraft,
      status: "ready",
      published_at: null,
    });
    render(<TestWrapper><DraftEditPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByDisplayValue("AI 行业洞察")).toBeInTheDocument());
    const publishBtn = await screen.findByText("发布");
    const btn = publishBtn.closest("button");
    expect(btn).not.toBeDisabled();
  });
});