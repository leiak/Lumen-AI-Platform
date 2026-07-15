// frontend/__tests__/workflow/designer.test.tsx
// Render-level smoke test: confirm the right panel is dispatched per node type.
// Uses shallow rendering by mocking all panel modules.
import { describe, expect, it, vi } from "vitest";

// Mock the actual panel components so we can assert which is rendered.
vi.mock("@/components/workflow/nodes/input/Panel", () => ({
  InputPanel: () => <div data-testid="input-panel">InputPanel</div>,
}));
vi.mock("@/components/workflow/nodes/agent/Panel", () => ({
  AgentPanel: () => <div data-testid="agent-panel">AgentPanel</div>,
}));
vi.mock("@/components/workflow/nodes/condition/Panel", () => ({
  ConditionPanel: () => <div data-testid="condition-panel">ConditionPanel</div>,
}));
vi.mock("@/components/workflow/nodes/output/Panel", () => ({
  OutputPanel: () => <div data-testid="output-panel">OutputPanel</div>,
}));
vi.mock("@/components/workflow/nodes/parallel/Panel", () => ({
  ParallelPanel: () => <div data-testid="parallel-panel">ParallelPanel</div>,
}));
vi.mock("@/components/workflow/nodes/fan_out/Panel", () => ({
  FanOutPanel: () => <div data-testid="fan_out-panel">FanOutPanel</div>,
}));
vi.mock("@/components/workflow/nodes/fan_in/Panel", () => ({
  FanInPanel: () => <div data-testid="fan_in-panel">FanInPanel</div>,
}));
vi.mock("@/components/workflow/nodes/llm/Panel", () => ({
  LLMPanel: () => <div data-testid="llm-panel">LLMPanel</div>,
}));
vi.mock("@/components/workflow/nodes/code/Panel", () => ({
  CodePanel: () => <div data-testid="code-panel">CodePanel</div>,
}));
vi.mock("@/components/workflow/nodes/http/Panel", () => ({
  HTTPPanel: () => <div data-testid="http-panel">HTTPPanel</div>,
}));
vi.mock("@/components/workflow/nodes/knowledge_retrieval/Panel", () => ({
  KBRetrievalPanel: () => (
    <div data-testid="kb-panel">KBRetrievalPanel</div>
  ),
}));
vi.mock("@/components/workflow/nodes/tool/Panel", () => ({
  ToolPanel: () => <div data-testid="tool-panel">ToolPanel</div>,
}));
vi.mock("@/components/workflow/nodes/template_transform/Panel", () => ({
  TemplateTransformPanel: () => <div data-testid="template-transform-panel">TemplateTransformPanel</div>,
}));
vi.mock("@/components/workflow/nodes/parameter_extractor/Panel", () => ({
  ParameterExtractorPanel: () => <div data-testid="parameter-extractor-panel">ParameterExtractorPanel</div>,
}));
vi.mock("@/components/workflow/nodes/question_classifier/Panel", () => ({
  QuestionClassifierPanel: () => <div data-testid="question-classifier-panel">QuestionClassifierPanel</div>,
}));
vi.mock("@/components/workflow/nodes/variable_assigner/Panel", () => ({
  VariableAssignerPanel: () => <div data-testid="variable-assigner-panel">VariableAssignerPanel</div>,
}));

import { render, screen } from "@testing-library/react";
import {
  PanelComponentMap,
  getPanelForType,
} from "@/components/workflow/nodes/registry";

describe("PanelComponentMap dispatch", () => {
  it.each([
    ["input", "input-panel"],
    ["agent", "agent-panel"],
    ["llm", "llm-panel"],
    ["condition", "condition-panel"],
    ["output", "output-panel"],
    ["parallel", "parallel-panel"],
    ["fan_out", "fan_out-panel"],
    ["fan_in", "fan_in-panel"],
    ["code", "code-panel"],
    ["http", "http-panel"],
    ["knowledge_retrieval", "kb-panel"],
    ["tool", "tool-panel"],
    ["template_transform", "template-transform-panel"],
    ["parameter_extractor", "parameter-extractor-panel"],
    ["question_classifier", "question-classifier-panel"],
    ["variable_assigner", "variable-assigner-panel"],
  ] as const)("returns %s panel for type %s", (type, testId) => {
    const Panel = getPanelForType(type);
    expect(Panel).toBeTruthy();
    if (!Panel) throw new Error(`No panel for ${type}`);
    render(
      <Panel
        node={{ id: "n1", type, config: {}, position: { x: 0, y: 0 } }}
        nodes={[]}
        edges={[]}
        onChange={() => {}}
      />
    );
    expect(screen.getByTestId(testId)).toBeTruthy();
  });

  it("returns null for unknown type", () => {
    expect(getPanelForType("start")).toBeNull();
  });
});
