import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ConfigProvider, App as AntdApp } from "antd";
import React from "react";

import { EditableKeyValueTable } from "@/components/workflow/nodes/http/EditableKeyValueTable";

function TestWrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider><AntdApp>{children}</AntdApp></ConfigProvider>;
}

describe("EditableKeyValueTable (M30c)", () => {
  it("renders a row for each existing entry", () => {
    const onChange = vi.fn();
    render(
      <TestWrapper>
        <EditableKeyValueTable
          value={{ "X-Foo": "bar", "X-Baz": "qux" }}
          onChange={onChange}
        />
      </TestWrapper>
    );
    expect(screen.getByDisplayValue("X-Foo")).toBeTruthy();
    expect(screen.getByDisplayValue("bar")).toBeTruthy();
    expect(screen.getByDisplayValue("X-Baz")).toBeTruthy();
  });

  it("renders the empty-state when value is empty", () => {
    render(
      <TestWrapper>
        <EditableKeyValueTable value={{}} onChange={vi.fn()} />
      </TestWrapper>
    );
    expect(screen.getByText(/暂无/)).toBeTruthy();
  });

  it("calls onChange when a new row is added", () => {
    const onChange = vi.fn();
    render(
      <TestWrapper>
        <EditableKeyValueTable value={{}} onChange={onChange} />
      </TestWrapper>
    );
    // Click the 添加 button.
    const addBtn = screen.getByText("添加");
    fireEvent.click(addBtn);
    expect(onChange).toHaveBeenCalled();
    const arg = onChange.mock.calls[0][0] as Record<string, string>;
    // The new row has a placeholder key.
    expect(Object.keys(arg).length).toBe(1);
  });

  it("calls onChange with the modified record when a value is edited", () => {
    const onChange = vi.fn();
    render(
      <TestWrapper>
        <EditableKeyValueTable
          value={{ "X-Foo": "bar" }}
          onChange={onChange}
        />
      </TestWrapper>
    );
    const valueInput = screen.getByDisplayValue("bar");
    fireEvent.change(valueInput, { target: { value: "new-value" } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ "X-Foo": "new-value" })
    );
  });

  it("removes a row when the delete button is clicked", () => {
    const onChange = vi.fn();
    render(
      <TestWrapper>
        <EditableKeyValueTable
          value={{ "X-Foo": "bar" }}
          onChange={onChange}
        />
      </TestWrapper>
    );
    // Find the danger delete button.
    const delBtn = document.querySelector(
      "button.ant-btn-dangerous"
    ) as HTMLElement;
    expect(delBtn).toBeTruthy();
    fireEvent.click(delBtn);
    expect(onChange).toHaveBeenCalledWith({});
  });
});
