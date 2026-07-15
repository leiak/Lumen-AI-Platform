// frontend/__tests__/image-generation/create-form.test.tsx
// M22 — image generation feature (T20)
//
// Tests for the CreateFormModal: validation when fields are missing, and
// happy path submit when a model + prompt are provided.
//
// Notes:
//   - The component's models query is only enabled when `open === true`, so
//     the modal must be rendered with `open`.
//   - The component's queryFn unwraps `res.data.data` from the AxiosResponse
//     envelope, so the mock must return the envelope shape:
//     `{ data: { code: 200, data: [...] } }`.
//   - The submit button label is "提交生成"; the placeholder for the model
//     Select is "请选择模型"; the prompt TextArea placeholder is
//     "描述你想生成的图片...".
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";
import { CreateFormModal } from "@/components/image-generation/CreateFormModal";

vi.mock("@/services/image-generation", () => ({
  imageGenerationApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn().mockResolvedValue({ id: 1, status: "pending" }),
    regenerate: vi.fn(),
    delete: vi.fn(),
    imagePath: (id: number) => `/image-generation/${id}/image`,
    thumbnailPath: (id: number) => `/image-generation/${id}/thumbnail`,
  },
}));

vi.mock("@/services/models", () => ({
  modelsApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    listTypes: vi.fn(),
    importFromOllama: vi.fn(),
    bulkCreate: vi.fn(),
  },
}));

const sampleModels = [
  {
    id: 1,
    name: "GPT-4o Image",
    model_type: "openai",
    model_name: "dall-e-3",
    is_image_generation: true,
    is_active: true,
    is_chat: false,
    is_embedding: false,
    is_default: false,
    temperature: 0,
    max_tokens: 0,
    timeout: 30,
    tenant_id: 1,
    created_at: "2026-06-11T00:00:00Z",
    updated_at: "2026-06-11T00:00:00Z",
  },
];

describe("CreateFormModal", () => {
  beforeEach(async () => {
    const { imageGenerationApi } = await import("@/services/image-generation");
    const { modelsApi } = await import("@/services/models");
    (imageGenerationApi.create as any).mockReset();
    (imageGenerationApi.create as any).mockResolvedValue({
      id: 1,
      status: "pending",
    });
    (modelsApi.list as any).mockReset();
    // The component's queryFn unwraps res.data.data, so the mock must
    // return the AxiosResponse envelope shape.
    (modelsApi.list as any).mockResolvedValue({
      data: { code: 200, message: "ok", data: sampleModels },
    });
  });

  it("requires model and prompt", async () => {
    render(
      <TestWrapper>
        <CreateFormModal open onClose={() => {}} />
      </TestWrapper>
    );
    // Wait for the form to be present (the submit button is the stable
    // element to look for — it lives in the footer, not behind any
    // conditional rendering).
    await waitFor(() =>
      expect(screen.getByText("提交生成")).toBeInTheDocument()
    );
    fireEvent.click(screen.getByText("提交生成"));
    await waitFor(() => {
      expect(
        screen.getByText("请选择图片生成模型")
      ).toBeInTheDocument();
    });
  });

  it("submits with valid input", async () => {
    const { imageGenerationApi } = await import("@/services/image-generation");
    render(
      <TestWrapper>
        <CreateFormModal open onClose={() => {}} />
      </TestWrapper>
    );
    // Wait for the submit button to be in the DOM (form is mounted).
    await waitFor(() =>
      expect(screen.getByText("提交生成")).toBeInTheDocument()
    );
    // Open the model Select via its combobox role (the established AntD v5
    // pattern in this repo — see EmbeddingModelSelect.test.tsx, KBSelector.test.tsx).
    // The form has multiple Selects (model, size, quality, style) so we
    // use getAllByRole and pick the first one (the model).
    // The dropdown options only render into a portal after mouseDown, so
    // the option text only appears post-open.
    fireEvent.mouseDown(screen.getAllByRole("combobox")[0]);
    // Wait for the option text to appear (it materializes in the dropdown).
    const option = await screen.findByText("GPT-4o Image (openai)");
    fireEvent.click(option);
    fireEvent.change(screen.getByPlaceholderText("描述你想生成的图片..."), {
      target: { value: "a cat" },
    });
    fireEvent.click(screen.getByText("提交生成"));
    await waitFor(() =>
      expect(imageGenerationApi.create).toHaveBeenCalled()
    );
    // Verify the actual payload rather than just call count — a "called"
    // assertion with wrong args would still pass.
    const call = (imageGenerationApi.create as any).mock.calls[0][0];
    expect(call.model_config_id).toBe(1);
    expect(call.prompt).toBe("a cat");
  });
});
