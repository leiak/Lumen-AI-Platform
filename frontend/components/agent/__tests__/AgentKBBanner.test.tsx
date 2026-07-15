import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ConfigProvider, App } from "antd";
import { AgentKBBanner } from "@/components/agent/AgentKBBanner";

const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider><App>{children}</App></ConfigProvider>
);

describe("AgentKBBanner", () => {
  it("renders banner with active and inactive KBs distinctly", () => {
    const agent = {
      id: 1,
      knowledge_bases: [
        { id: 10, name: "Active KB", status: "active" as const },
        { id: 20, name: "Inactive KB", status: "inactive" as const },
        { id: 30, name: "Deleted KB", status: "deleted" as const },
      ],
    } as any;

    render(<TestWrapper><AgentKBBanner agent={agent} /></TestWrapper>);

    expect(screen.getByText("Active KB")).toBeInTheDocument();
    expect(screen.getByText(/Inactive KB/)).toBeInTheDocument();
    // The deleted tag text is "⚠️ (已删除) Deleted KB" — it's a single text node
    // inside the Tag, so we need a function matcher to find it.
    expect(
      screen.getByText((_content, element) => {
        return (
          element?.tagName === "SPAN" &&
          (element.textContent ?? "").includes("已删除") &&
          (element.textContent ?? "").includes("Deleted KB")
        );
      })
    ).toBeInTheDocument();
  });

  it("calls onClose when close button clicked", () => {
    const onClose = vi.fn();
    const agent = {
      id: 1,
      knowledge_bases: [
        { id: 10, name: "Active KB", status: "active" as const },
      ],
    } as any;

    const { container } = render(
      <TestWrapper>
        <AgentKBBanner agent={agent} onClose={onClose} />
      </TestWrapper>
    );

    // The only button inside the banner is the close button
    const closeBtn = container.querySelector("div[style*='background'] button") as HTMLButtonElement;
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("returns null when no KBs bound", () => {
    const agent = { id: 1, knowledge_bases: [] } as any;
    const { container } = render(
      <TestWrapper><AgentKBBanner agent={agent} /></TestWrapper>
    );
    // The component returns null, so there should be no styled banner div
    const banner = container.querySelector("div[style*='background']");
    expect(banner).toBeNull();
  });

  it("returns null when knowledge_bases is undefined", () => {
    const agent = { id: 1 } as any;
    const { container } = render(
      <TestWrapper><AgentKBBanner agent={agent} /></TestWrapper>
    );
    const banner = container.querySelector("div[style*='background']");
    expect(banner).toBeNull();
  });
});
