import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConditionCaseEditor, ConditionCase } from "@/components/workflow/_base/condition/ConditionCaseEditor";

const baseProps = { nodeId: "n1", nodes: [], edges: [] };

describe("ConditionCaseEditor", () => {
  it("renders existing cases", () => {
    const cases: ConditionCase[] = [
      { case_id: "a3f2", logical_operator: "and", conditions: [] },
    ];
    render(<ConditionCaseEditor {...baseProps} cases={cases} onChange={() => {}} />);
    expect(screen.getByText(/a3f2/)).toBeTruthy();
  });

  it("adds a new case with unique case_id on button click", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<ConditionCaseEditor {...baseProps} cases={[]} onChange={onChange} />);
    await user.click(screen.getByText(/添加 Case/));
    expect(onChange).toHaveBeenCalledTimes(1);
    const newCases = onChange.mock.calls[0][0];
    expect(newCases.length).toBe(1);
    expect(newCases[0].case_id).toBeTruthy();
  });

  it("changes logical_operator to or", async () => {
    const onChange = vi.fn();
    const cases: ConditionCase[] = [
      { case_id: "c1", logical_operator: "and", conditions: [] },
    ];
    const user = userEvent.setup();
    render(<ConditionCaseEditor {...baseProps} cases={cases} onChange={onChange} />);
    // AntD Radio.Button hides the <input> (pointer-events: none) and uses the label as the click target.
    await user.click(screen.getByText("OR"));
    expect(onChange).toHaveBeenCalledWith([
      { case_id: "c1", logical_operator: "or", conditions: [] },
    ]);
  });

  it("removes a condition when its delete button is clicked", async () => {
    const onChange = vi.fn();
    const cases: ConditionCase[] = [
      {
        case_id: "c1",
        logical_operator: "and",
        conditions: [
          { variable_selector: ["n1", "x"], comparison_operator: "=", value: "1" },
        ],
      },
    ];
    const user = userEvent.setup();
    const { container } = render(
      <ConditionCaseEditor {...baseProps} cases={cases} onChange={onChange} />
    );
    const deleteBtn = container.querySelector(".ant-btn-icon-only") as HTMLElement;
    await user.click(deleteBtn);
    expect(onChange).toHaveBeenCalledWith([
      { case_id: "c1", logical_operator: "and", conditions: [] },
    ]);
  });
});
