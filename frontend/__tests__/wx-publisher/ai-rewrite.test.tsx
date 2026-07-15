// frontend/__tests__/wx-publisher/ai-rewrite.test.tsx
// M32 — 公众号助手 — AIRewriteModal tests (component-level).
// 3 cases: 表单 / Diff 对比 / 提交调 API.
import { describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TestWrapper } from "./test-utils";
import { AIRewriteModal } from "@/components/wx-publisher/AIRewriteModal";

const sampleSection = {
  id: 10,
  order_index: 0,
  heading: "一、背景",
  content_markdown: "原内容\n第二行\n第三行",
  content_html: null,
  ai_prompt: null,
  ai_model_config_id: null,
};

describe("AIRewriteModal", () => {
  it("renders rewrite form when opened with action=rewrite", () => {
    render(
      <TestWrapper>
        <AIRewriteModal
          open={true}
          action="rewrite"
          section={sampleSection}
          onCancel={() => {}}
          onSubmit={() => {}}
        />
      </TestWrapper>
    );
    expect(screen.getByText("AI 改写")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/改得更口语化/)).toBeInTheDocument();
    expect(screen.getByText("确认改写")).toBeInTheDocument();
  });

  it("shows diff comparison after result provided", async () => {
    // 模拟调用方: onSubmit → 拿到 new_content 后 prop 传入 + 显示 diff.
    // AIRewriteModal 内部 submitted state 触发 diff 视图; 这里走 onSubmit
    // 拿到 newContent 后 re-render.
    const newContent = "新内容\n第二行\n新第三行";
    const Wrapper = () => {
      const [content, setContent] = React.useState<string | null>(null);
      return (
        <AIRewriteModal
          open={true}
          action="rewrite"
          section={sampleSection}
          newContent={content}
          onCancel={() => {}}
          onSubmit={() => {
            setContent(newContent);
          }}
        />
      );
    };
    render(
      <TestWrapper>
        <Wrapper />
      </TestWrapper>
    );
    // 先填 instruction (form.required rule) 再点确认改写.
    const textarea = screen.getByPlaceholderText(/改得更口语化/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "改得更口语化" } });
    fireEvent.click(screen.getByText("确认改写"));
    // diff 视图出现: "新内容 (Diff)" 标题 + 原内容 column.
    await waitFor(() =>
      expect(screen.getByText("新内容 (Diff)")).toBeInTheDocument()
    );
    // 原内容 column 显示 section.content_markdown 第一行.
    expect(screen.getByText("原内容")).toBeInTheDocument();
    // 新内容行在 diff 内 (绿底) — 文本节点 broken-up by span, 用 querySelector
    // 找带 "新内容" 文字的 .diff/added 容器.
    const addedNode = Array.from(document.querySelectorAll("pre div")).find(
      (d) => d.textContent === "+ 新内容"
    );
    expect(addedNode).toBeDefined();
  });

  it("calls onSubmit with instruction text", async () => {
    const onSubmit = vi.fn();
    render(
      <TestWrapper>
        <AIRewriteModal
          open={true}
          action="rewrite"
          section={sampleSection}
          onCancel={() => {}}
          onSubmit={onSubmit}
        />
      </TestWrapper>
    );
    const textarea = screen.getByPlaceholderText(/改得更口语化/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "改成更口语化" } });
    fireEvent.click(screen.getByText("确认改写"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith("改成更口语化", undefined));
  });
});