// frontend/services/vision.ts
import api from "./auth";

export interface VisionClassification {
  id: number;
  name: string;
  description?: string;
  tenant_id?: number;
  created_at: string;
}

export interface VisionImage {
  id: number;
  filename: string;
  file_path: string;
  classification_id: number;
  features?: Record<string, any>;
  tenant_id?: number;
  created_at: string;
}

/** Architecture options surfaced in the training config form. */
export type VisionArchitecture =
  | "logistic_regression"
  | "resnet18"
  | "resnet50"
  | "vgg16"
  | "vit_small"
  | "vit_base";

export interface VisionTrainingConfig {
  classification_id: number;
  architecture: VisionArchitecture;
  epochs: number;
  batch_size: number;
  image_size: number;
  learning_rate: number;
  train_test_split: number; // 0..1
  augment: boolean;
}

export interface TrainResult {
  status: string;
  model_path?: string;
  accuracy?: number;
  message: string;
}

export interface PredictResult {
  predicted_class_id?: number;
  confidence?: number;
  error?: string;
}

/** A locally-pending image with an object-URL preview, before upload. */
export interface PendingImage {
  uid: string;
  file: File;
  previewUrl: string;
}

export const VISION_ARCHITECTURE_LABELS: Record<VisionArchitecture, string> = {
  logistic_regression: "Logistic Regression (built-in)",
  resnet18: "ResNet-18",
  resnet50: "ResNet-50",
  vgg16: "VGG-16",
  vit_small: "ViT-Small",
  vit_base: "ViT-Base",
};

export const DEFAULT_TRAINING_CONFIG: Omit<
  VisionTrainingConfig,
  "classification_id"
> = {
  architecture: "logistic_regression",
  epochs: 10,
  batch_size: 32,
  image_size: 64,
  learning_rate: 0.001,
  train_test_split: 0.2,
  augment: false,
};

/** Build a client-side object URL for a freshly-selected image file. */
export function createImagePreviewUrl(file: File): string {
  return URL.createObjectURL(file);
}

/** Release a previously-created preview URL to avoid memory leaks. */
export function revokeImagePreviewUrl(url: string | null | undefined): void {
  if (!url) return;
  try {
    URL.revokeObjectURL(url);
  } catch {
    /* ignore — URL may already be revoked */
  }
}

export const visionApi = {
  // Classification
  listClassifications: (page = 1, pageSize = 100) =>
    api.get<any>(`/vision/classification/?page=${page}&page_size=${pageSize}`),
  createClassification: (data: Partial<VisionClassification>) =>
    api.post<any>("/vision/classification/", data),
  deleteClassification: (id: number) =>
    api.delete<any>(`/vision/classification/${id}`),

  // Image
  listImages: (classificationId?: number, page = 1, pageSize = 100) =>
    classificationId
      ? api.get<any>(`/vision/image/?classification_id=${classificationId}&page=${page}&page_size=${pageSize}`)
      : api.get<any>(`/vision/image/?page=${page}&page_size=${pageSize}`),
  uploadImage: (classificationId: number, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return api.post<any>(`/vision/image/?classification_id=${classificationId}`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  deleteImage: (id: number) =>
    api.delete<any>(`/vision/image/${id}`),

  // Training
  /**
   * The backend currently only supports synchronous training with a
   * hard-coded model. The config object is forwarded for forward
   * compatibility — extra keys are ignored by the existing endpoint.
   */
  train: (config: VisionTrainingConfig) =>
    api.post<any>("/vision/train", { classification_id: config.classification_id, config }),
  predict: (imageId: number, classificationId: number) =>
    api.post<any>("/vision/predict", { image_id: imageId, classification_id: classificationId }),
};
