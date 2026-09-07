/**
 * M30c 2.0 (2026-09-07): 11 Node.tsx smoke tests, consolidated into one file.
 * The plan called for 11 separate test files but they're all smoke tests
 * with identical shape (render + props) — one file with 11 describe blocks
 * is easier to maintain.
 *
 * Covers 8 P1 nodes (input/agent/llm/condition/output/parallel/fan_out/fan_in)
 * + 3 M35/M36 nodes (tts/playbook_inject/video_compose) — the 9 P2 nodes
 * already had Node.tsx smoke coverage from M30 (2026-06-05).
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConfigProvider, App as AntdApp } from "antd";
import { ReactFlowProvider } from "@xyflow/react";

import { InputNode } from "@/components/workflow/nodes/input/Node";
import { AgentNode } from "@/components/workflow/nodes/agent/Node";
import { LLMNode } from "@/components/workflow/nodes/llm/Node";
import { ConditionNode } from "@/components/workflow/nodes/condition/Node";
import { OutputNode } from "@/components/workflow/nodes/output/Node";
import { ParallelNode } from "@/components/workflow/nodes/parallel/Node";
import { FanOutNode } from "@/components/workflow/nodes/fan_out/Node";
import { FanInNode } from "@/components/workflow/nodes/fan_in/Node";
import { TTSNode } from "@/components/workflow/nodes/tts/Node";
import { PlaybookInjectNode } from "@/components/workflow/nodes/playbook_inject/Node";
import { VideoComposeNode } from "@/components/workflow/nodes/video_compose/Node";

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <ConfigProvider>
      <AntdApp>
        <ReactFlowProvider>{children}</ReactFlowProvider>
      </AntdApp>
    </ConfigProvider>
  );
}

describe("M30c Node.tsx smoke tests", () => {
  describe("InputNode (P1)", () => {
    it("renders without crashing and shows label", () => {
      const { container } = render(
        <Wrapper>
          <InputNode data={{ label: "Start" }} />
        </Wrapper>
      );
      expect(container.textContent).toContain("Start");
    });
    it("renders default label when data.label missing", () => {
      const { container } = render(
        <Wrapper>
          <InputNode data={{}} />
        </Wrapper>
      );
      expect(container.textContent).toBeTruthy();
    });
  });

  describe("AgentNode (P1)", () => {
    it("renders label from data", () => {
      const { container } = render(
        <Wrapper>
          <AgentNode data={{ label: "My Agent" }} />
        </Wrapper>
      );
      expect(container.textContent).toContain("My Agent");
    });
  });

  describe("LLMNode (P1)", () => {
    it("renders label from data", () => {
      const { container } = render(
        <Wrapper>
          <LLMNode data={{ label: "My LLM" }} />
        </Wrapper>
      );
      expect(container.textContent).toContain("My LLM");
    });
  });

  describe("ConditionNode (P1)", () => {
    it("renders label from data", () => {
      const { container } = render(
        <Wrapper>
          <ConditionNode data={{ label: "If yes" }} />
        </Wrapper>
      );
      expect(container.textContent).toContain("If yes");
    });
  });

  describe("OutputNode (P1)", () => {
    it("renders label from data", () => {
      const { container } = render(
        <Wrapper>
          <OutputNode data={{ label: "End" }} />
        </Wrapper>
      );
      expect(container.textContent).toContain("End");
    });
  });

  describe("ParallelNode (P1)", () => {
    it("renders label from data", () => {
      const { container } = render(
        <Wrapper>
          <ParallelNode data={{ label: "Parallel Branch" }} />
        </Wrapper>
      );
      expect(container.textContent).toContain("Parallel Branch");
    });
  });

  describe("FanOutNode (P1)", () => {
    it("renders label from data", () => {
      const { container } = render(
        <Wrapper>
          <FanOutNode data={{ label: "Fan Out" }} />
        </Wrapper>
      );
      expect(container.textContent).toContain("Fan Out");
    });
  });

  describe("FanInNode (P1)", () => {
    it("renders label from data", () => {
      const { container } = render(
        <Wrapper>
          <FanInNode data={{ label: "Fan In" }} />
        </Wrapper>
      );
      expect(container.textContent).toContain("Fan In");
    });
  });

  describe("TTSNode (M35)", () => {
    it("renders with default voice label", () => {
      const { container } = render(
        <Wrapper>
          <TTSNode data={{ label: "Say Hi" }} />
        </Wrapper>
      );
      expect(container.textContent).toContain("Say Hi");
    });
  });

  describe("PlaybookInjectNode (M35)", () => {
    it("renders target tag from data.target", () => {
      const { container } = render(
        <Wrapper>
          <PlaybookInjectNode data={{ label: "Inject", target: "tts_text" }} />
        </Wrapper>
      );
      expect(container.textContent).toContain("tts_text");
    });
    it("falls back to image_prompt target when missing", () => {
      const { container } = render(
        <Wrapper>
          <PlaybookInjectNode data={{}} />
        </Wrapper>
      );
      expect(container.textContent).toContain("image_prompt");
    });
  });

  describe("VideoComposeNode (M36)", () => {
    it("renders image count from source_images array", () => {
      const { container } = render(
        <Wrapper>
          <VideoComposeNode
            data={{ label: "Compose", source_images: ["a.png", "b.png", "c.png"] }}
          />
        </Wrapper>
      );
      expect(container.textContent).toContain("3");
    });
    it("renders 0 when source_images missing", () => {
      const { container } = render(
        <Wrapper>
          <VideoComposeNode data={{}} />
        </Wrapper>
      );
      // Tag should still render with × 0
      expect(container.textContent).toMatch(/×\s*0/);
    });
  });
});
