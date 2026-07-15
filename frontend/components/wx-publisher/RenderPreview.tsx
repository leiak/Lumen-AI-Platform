// frontend/components/wx-publisher/RenderPreview.tsx
// M32.1 — 公众号助手 — 实时预览 (右侧列, 升级:加 电脑/手机 切换).
//
// 借鉴 lark-to-markdown-main/components/PreviewPanel.tsx 思路:
// - 顶部 Segmented 切换 电脑 / 手机 视图
// - 手机模式:360px 宽 + status bar (44px) + home indicator
// - 两种视图都用同一份 html(srcDoc)
//
// Spec §5.3 — iframe srcdoc 注入, 节流 500ms 避免每次 keyup 触发 render.
// 该组件本身不做节流 — 由父组件 DraftEditor 通过 debounced state 传入.
"use client";

import { useState } from "react";
import { Empty, Segmented } from "antd";
import {
  DesktopOutlined,
  MobileOutlined,
  FullscreenOutlined,
} from "@ant-design/icons";

interface RenderPreviewProps {
  html: string | null;
  height?: number;
}

const MOBILE_WIDTH = 375; // iPhone 14 Pro logical width

export function RenderPreview({ html, height = 500 }: RenderPreviewProps) {
  const [view, setView] = useState<"desktop" | "mobile">("desktop");

  if (!html) {
    return (
      <div
        style={{
          height,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#fafafa",
          border: "1px dashed #d9d9d9",
          borderRadius: 4,
        }}
      >
        <Empty description="点击「应用模板」生成预览" />
      </div>
    );
  }

  return (
    <div>
      {/* 顶部视图切换 — 借鉴 lark PreviewPanel */}
      <div
        style={{
          marginBottom: 8,
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <Segmented
          value={view}
          onChange={(v) => setView(v as "desktop" | "mobile")}
          options={[
            {
              label: (
                <span>
                  <DesktopOutlined /> 电脑
                </span>
              ),
              value: "desktop",
            },
            {
              label: (
                <span>
                  <MobileOutlined /> 手机 ({MOBILE_WIDTH}px)
                </span>
              ),
              value: "mobile",
            },
          ]}
        />
        <span
          style={{
            fontSize: 11,
            color: "#9ca3af",
            marginLeft: 4,
          }}
        >
          <FullscreenOutlined /> 真实模板渲染效果
        </span>
      </div>

      {view === "desktop" ? (
        <iframe
          title="render-preview-desktop"
          srcDoc={html}
          sandbox="allow-same-origin"
          style={{
            width: "100%",
            height,
            border: "1px solid #d9d9d9",
            borderRadius: 4,
            background: "#fff",
          }}
        />
      ) : (
        <PhoneFrame html={html} contentHeight={height} />
      )}
    </div>
  );
}

// --- 手机框模拟器 --------------------------------------------------------
// 360px 宽 (用 375 px max-width 装下 iPhone 14 Pro 实际宽度)
// 顶部 status bar (44px) + 中部 iframe (动态填充) + 底部 home indicator (34px)
// 借鉴 lark PreviewPanel 但独立实现(项目无 Tailwind / React Icons)。

function PhoneFrame({
  html,
  contentHeight,
}: {
  html: string;
  contentHeight: number;
}) {
  // status bar 44px + home indicator 34px = 78px 减掉
  const innerHeight = Math.max(200, contentHeight - 78);
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "center",
        padding: "8px 0",
        background: "#f3f4f6",
        borderRadius: 8,
      }}
    >
      <div
        style={{
          width: MOBILE_WIDTH,
          maxWidth: "100%",
          background: "#fff",
          borderRadius: 24,
          boxShadow: "0 4px 16px rgba(0,0,0,0.12)",
          overflow: "hidden",
          border: "1px solid #d1d5db",
        }}
      >
        {/* Status bar — 44px 白底,中间黑色 notch 模拟 */}
        <div
          style={{
            height: 44,
            background: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            position: "relative",
            borderBottom: "1px solid #f3f4f6",
          }}
        >
          <div
            style={{
              position: "absolute",
              top: 8,
              left: "50%",
              transform: "translateX(-50%)",
              width: 100,
              height: 24,
              background: "#000",
              borderRadius: 12,
            }}
          />
          <span
            style={{
              position: "absolute",
              left: 16,
              top: 14,
              fontSize: 12,
              fontWeight: 600,
              color: "#111",
            }}
          >
            9:41
          </span>
        </div>

        {/* 中部 iframe — 公众号文章渲染 */}
        <iframe
          title="render-preview-mobile"
          srcDoc={html}
          sandbox="allow-same-origin"
          style={{
            width: "100%",
            height: innerHeight,
            border: "none",
            background: "#fff",
            display: "block",
          }}
        />

        {/* Home indicator — iPhone 底部小横条 */}
        <div
          style={{
            height: 34,
            background: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <div
            style={{
              width: 120,
              height: 5,
              background: "#111",
              borderRadius: 3,
            }}
          />
        </div>
      </div>
    </div>
  );
}

export default RenderPreview;