// frontend/__tests__/workflow/_base/variable/utils.test.ts
import { describe, expect, it } from "vitest";
import { BlockEnum, VarType } from "@/components/workflow/_base/variable/types";
import { formatItem } from "@/components/workflow/_base/variable/utils";

const mkNode = (type: string, id: string, config: any = {}) => ({
  id,
  type,
  config,
  position: { x: 0, y: 0 },
});

describe("formatItem", () => {
  it("returns default value variable for InputNode with no config", () => {
    const vars = formatItem(mkNode(BlockEnum.Input, "n1") as any);
    expect(vars.find((v) => v.variable === "value")).toBeTruthy();
  });

  it("returns user-defined variables for InputNode with config", () => {
    const vars = formatItem(
      mkNode(BlockEnum.Input, "n1", {
        variables: [
          { name: "user_query", type: VarType.string },
          { name: "count", type: VarType.number },
        ],
      }) as any
    );
    expect(vars.map((v) => v.variable)).toEqual(["user_query", "count"]);
  });

  it("returns 4 LLM outputs in order", () => {
    const vars = formatItem(mkNode(BlockEnum.LLM, "n1") as any);
    const names = vars.map((v) => v.variable);
    expect(names).toEqual(["response", "model", "finish_reason", "usage"]);
    expect(vars.find((v) => v.variable === "response")?.type).toBe(VarType.string);
    expect(vars.find((v) => v.variable === "usage")?.type).toBe(VarType.object);
  });

  it("returns ConditionNode outputs with boolean result", () => {
    const vars = formatItem(mkNode(BlockEnum.Condition, "n1") as any);
    expect(vars.find((v) => v.variable === "result")?.type).toBe(VarType.boolean);
    expect(vars.find((v) => v.variable === "selected_case_id")?.type).toBe(VarType.string);
  });

  it("returns FanOut results as array[object]", () => {
    const vars = formatItem(mkNode(BlockEnum.FanOut, "n1") as any);
    expect(vars[0].type).toBe(VarType.arrayObject);
  });

  it("returns FanIn result + count", () => {
    const vars = formatItem(mkNode(BlockEnum.FanIn, "n1") as any);
    const names = vars.map((v) => v.variable);
    expect(names).toEqual(["result", "count"]);
  });

  it("returns empty array for unknown node type", () => {
    const vars = formatItem(mkNode("unknown_type", "n1") as any);
    expect(vars).toEqual([]);
  });
});
