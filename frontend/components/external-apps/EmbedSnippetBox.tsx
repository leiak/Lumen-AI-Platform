"use client";

import { useState } from "react";
import { Input, Button, Space, App } from "antd";
import { CopyOutlined } from "@ant-design/icons";

interface Props {
  serverUrl: string;
  appKey: string;
  defaultAgentId?: number;
}

export default function EmbedSnippetBox({ serverUrl, appKey, defaultAgentId }: Props) {
  const { message } = App.useApp();
  const agentAttr = defaultAgentId ? `\n    agent-id="${defaultAgentId}"` : "";
  const snippet = `<script src="${serverUrl}/static/widget/lc-chat.js"></script>
<lc-chat
    server="${serverUrl}"
    app-key="${appKey}"${agentAttr}
    theme="auto">
</lc-chat>`;
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(snippet);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
      message.success("已复制");
    } catch {
      message.error("复制失败");
    }
  }

  return (
    <Space.Compact style={{ width: "100%" }}>
      <Input.TextArea readOnly value={snippet} autoSize={{ minRows: 5, maxRows: 10 }} />
      <Button icon={<CopyOutlined />} onClick={copy}>{copied ? "已复制" : "复制"}</Button>
    </Space.Compact>
  );
}
