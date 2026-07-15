import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { ToolSelector } from "@/components/workflow/ToolSelector";

vi.mock("@/services/mcp", () => ({
  mcpApi: {
    listTools: vi.fn(),
  },
}));

import { mcpApi } from "@/services/mcp";

const wrap = (ui: React.ReactNode) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{ui}</ConfigProvider>
);

describe("ToolSelector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists active tools only and skips disabled ones", async () => {
    (mcpApi.listTools as any).mockResolvedValue({
      data: {
        code: 200,
        data: [
          {
            id: 1,
            name: "search",
            description: "搜索工具",
            input_schema: {},
            server_name: "local-demo",
            is_enabled: 1,
          },
          {
            id: 2,
            name: "inactive",
            description: "旧工具",
            input_schema: {},
            server_name: "local-demo",
            is_enabled: 0,
          },
        ],
        total: 2,
        page: 1,
        page_size: 10,
      },
    });

    render(
      wrap(
        <ToolSelector
          value={null}
          toolNameCache=""
          onChange={() => {}}
        />
      )
    );

    fireEvent.mouseDown(screen.getByRole("combobox"));
    await waitFor(() => {
      expect(screen.getByText("search")).toBeInTheDocument();
    });
    expect(screen.queryByText("inactive")).not.toBeInTheDocument();
  });

  it("shows the missing yellow entry when value references a deleted tool", async () => {
    (mcpApi.listTools as any).mockResolvedValue({
      data: {
        code: 200,
        data: [
          {
            id: 1,
            name: "search",
            description: "搜索工具",
            input_schema: {},
            server_name: "local-demo",
            is_enabled: 1,
          },
        ],
        total: 1,
        page: 1,
        page_size: 10,
      },
    });

    render(
      wrap(
        <ToolSelector
          value={999}
          toolNameCache="old-tool"
          onChange={() => {}}
        />
      )
    );

    // The cached name surfaces in the warning row below the Select
    expect(screen.getByText(/原工具已失效/)).toBeInTheDocument();

    // Opening the dropdown reveals the missing-sentinel option (matched
    // by aria-label, since AntD puts the value in the text node)
    fireEvent.mouseDown(screen.getByRole("combobox"));
    await waitFor(() => {
      expect(
        screen.getByRole("option", { name: /已删除/ })
      ).toBeInTheDocument();
    });
  });
});
