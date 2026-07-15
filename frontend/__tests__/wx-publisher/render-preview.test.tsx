// frontend/__tests__/wx-publisher/render-preview.test.tsx
// M32.1 — RenderPreview component deep DOM structure verification.
//
// 验证:
// - 桌面模式:iframe title="render-preview-desktop", sandbox allow-same-origin
// - 手机模式:iframe title="render-preview-mobile", 内嵌 PhoneFrame 结构
//   - 状态栏 9:41 + 黑色 notch
//   - 主内容区 iframe
//   - 底部 home indicator (120×5 灰色圆角条)
// - 切换: 点击 Segmented 切换模式后,旧 iframe 消失,新 iframe 出现

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RenderPreview } from "@/components/wx-publisher/RenderPreview";
import { TestWrapper } from "./test-utils";

const sampleHtml = `<!DOCTYPE html><html><body><h1>公众号文章预览</h1><p>这是 <strong>渲染</strong> 内容.</p></body></html>`;

describe("RenderPreview", () => {
  beforeEach(() => {
    // 每个测试前重置 iframe sandbox 状态(测试间可能共享 jsdom)
  });

  it("renders empty state when html is null", () => {
    render(
      <TestWrapper>
        <RenderPreview html={null} />
      </TestWrapper>
    );
    expect(screen.getByText(/点击「应用模板」生成预览/)).toBeInTheDocument();
  });

  describe("desktop mode (default)", () => {
    it("renders iframe with correct title and srcDoc", () => {
      render(
        <TestWrapper>
          <RenderPreview html={sampleHtml} />
        </TestWrapper>
      );
      const iframe = screen.getByTitle("render-preview-desktop") as HTMLIFrameElement;
      expect(iframe).toBeInTheDocument();
      // jsdom 不实现 srcDoc 属性 — 用 srcdoc attribute 直读(React 渲染时
      // HTMLIFrameElement.srcdoc 是 lowercase,而 DOM property 是 srcDoc)
      const srcdocAttr = iframe.getAttribute("srcdoc");
      expect(srcdocAttr).toBe(sampleHtml);
      // sandbox 属性直读 — jsdom 不支持 sandbox.toString()
      const sandboxAttr = iframe.getAttribute("sandbox") || "";
      expect(sandboxAttr).toContain("allow-same-origin");
      expect(sandboxAttr).not.toContain("allow-scripts");
    });

    it("renders Segmented with 电脑/手机 options", () => {
      render(
        <TestWrapper>
          <RenderPreview html={sampleHtml} />
        </TestWrapper>
      );
      expect(screen.getByText(/^电脑$/)).toBeInTheDocument();
      expect(screen.getByText(/手机 \(375px\)/)).toBeInTheDocument();
    });

    it("does NOT render phone frame structure in desktop mode", () => {
      const { container } = render(
        <TestWrapper>
          <RenderPreview html={sampleHtml} />
        </TestWrapper>
      );
      // 手机模式专属元素不应在桌面模式出现
      expect(container.querySelector(".anticon-mobile")).toBeInTheDocument(); // Segmented icon
      expect(screen.queryByText("9:41")).not.toBeInTheDocument();
    });
  });

  describe("mobile mode", () => {
    it("switches to mobile iframe when 手机 clicked", async () => {
      render(
        <TestWrapper>
          <RenderPreview html={sampleHtml} />
        </TestWrapper>
      );
      // 初始:桌面 iframe
      expect(screen.getByTitle("render-preview-desktop")).toBeInTheDocument();
      // 点击「手机」
      fireEvent.click(screen.getByText(/手机 \(375px\)/));
      // 桌面 iframe 消失,手机 iframe 出现
      await waitFor(() => {
        expect(screen.queryByTitle("render-preview-desktop")).not.toBeInTheDocument();
      });
      expect(screen.getByTitle("render-preview-mobile")).toBeInTheDocument();
    });

    it("renders phone frame structure: status bar with 9:41 + notch", async () => {
      const { container } = render(
        <TestWrapper>
          <RenderPreview html={sampleHtml} />
        </TestWrapper>
      );
      fireEvent.click(screen.getByText(/手机 \(375px\)/));
      await waitFor(() => {
        expect(screen.getByTitle("render-preview-mobile")).toBeInTheDocument();
      });

      // 状态栏时间 — lark 风格顶部 "9:41"
      expect(screen.getByText("9:41")).toBeInTheDocument();
      // 手机框宽度约束 375px
      const phoneFrame = container.querySelector(
        "div[style*='width: 375px']"
      );
      expect(phoneFrame).toBeInTheDocument();
    });

    it("renders home indicator (120×5 圆角条)", async () => {
      const { container } = render(
        <TestWrapper>
          <RenderPreview html={sampleHtml} />
        </TestWrapper>
      );
      fireEvent.click(screen.getByText(/手机 \(375px\)/));
      await waitFor(() => {
        expect(screen.getByTitle("render-preview-mobile")).toBeInTheDocument();
      });

      // home indicator — 120×5 px 灰色圆角条
      const homeIndicator = container.querySelector(
        "div[style*='width: 120px'][style*='height: 5px'][style*='border-radius: 3px']"
      );
      expect(homeIndicator).toBeInTheDocument();
    });

    it("mobile iframe srcDoc matches input html", async () => {
      render(
        <TestWrapper>
          <RenderPreview html={sampleHtml} />
        </TestWrapper>
      );
      fireEvent.click(screen.getByText(/手机 \(375px\)/));
      await waitFor(() => {
        expect(screen.getByTitle("render-preview-mobile")).toBeInTheDocument();
      });
      const mobileIframe = screen.getByTitle("render-preview-mobile") as HTMLIFrameElement;
      expect(mobileIframe.getAttribute("srcdoc")).toBe(sampleHtml);
      const sandboxAttr = mobileIframe.getAttribute("sandbox") || "";
      expect(sandboxAttr).toContain("allow-same-origin");
      expect(sandboxAttr).not.toContain("allow-scripts");
    });
  });

  describe("security", () => {
    it("iframe sandbox does not allow scripts (XSS protection)", () => {
      render(
        <TestWrapper>
          <RenderPreview html={sampleHtml} />
        </TestWrapper>
      );
      const iframe = screen.getByTitle("render-preview-desktop") as HTMLIFrameElement;
      // allow-same-origin 必须有 (iframe 内访问同源资源), allow-scripts 必须无
      const sandboxAttr = iframe.getAttribute("sandbox") || "";
      expect(sandboxAttr).toContain("allow-same-origin");
      expect(sandboxAttr).not.toContain("allow-scripts");
    });
  });
});