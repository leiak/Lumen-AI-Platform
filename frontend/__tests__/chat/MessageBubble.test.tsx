/**
 * Tests for MessageBubble's web-search-status notice.
 *
 * Background: when the user toggles "联网搜索" on, the backend
 * (chat_features.ChatFeatureService) tags the assistant message with
 * `metadata.search_status` ∈ {disabled, ok, empty, error}. The UI must
 * surface a notice for "empty" / "error" so the user understands why
 * the model gave a canned "I cannot search" response.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { MessageBubble } from "@/components/chat/MessageBubble";
import type { Message } from "@/types/chat";

// AntD's autoInsertSpace only affects <Button> children, but we wrap
// for safety / consistency with other test files.
const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{children}</ConfigProvider>
);

const baseMsg: Message = {
  id: 1,
  conversation_id: 1,
  role: "assistant",
  content: "Here is the answer based on the search results.",
  created_at: new Date().toISOString(),
};

describe("MessageBubble search-status notice", () => {
  it("renders a notice when search_status is 'empty'", () => {
    render(
      <MessageBubble
        message={{ ...baseMsg, metadata: { search_status: "empty" } }}
      />,
      { wrapper: TestWrapper }
    );
    expect(screen.getByTestId("search-status-notice")).toBeInTheDocument();
  });

  it("renders a notice when search_status is 'error'", () => {
    render(
      <MessageBubble
        message={{ ...baseMsg, metadata: { search_status: "error" } }}
      />,
      { wrapper: TestWrapper }
    );
    expect(screen.getByTestId("search-status-notice")).toBeInTheDocument();
  });

  it("does NOT render a notice when search_status is 'ok'", () => {
    render(
      <MessageBubble
        message={{ ...baseMsg, metadata: { search_status: "ok" } }}
      />,
      { wrapper: TestWrapper }
    );
    expect(screen.queryByTestId("search-status-notice")).not.toBeInTheDocument();
  });

  it("does NOT render a notice when search_status is 'disabled'", () => {
    render(
      <MessageBubble
        message={{ ...baseMsg, metadata: { search_status: "disabled" } }}
      />,
      { wrapper: TestWrapper }
    );
    expect(screen.queryByTestId("search-status-notice")).not.toBeInTheDocument();
  });

  it("does NOT render a notice when metadata is absent", () => {
    render(<MessageBubble message={{ ...baseMsg }} />, { wrapper: TestWrapper });
    expect(screen.queryByTestId("search-status-notice")).not.toBeInTheDocument();
  });
});
