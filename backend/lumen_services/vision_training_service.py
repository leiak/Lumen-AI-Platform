import os
import joblib
from typing import List

from PIL import Image
import numpy as np

from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score


class VisionTrainingService:
    """Vision 图像分类训练服务"""

    def __init__(self):
        self.model_dir = "./models/vision"
        os.makedirs(self.model_dir, exist_ok=True)

    def _extract_features(self, image_path: str) -> np.ndarray:
        """Extract features from an image using color histogram.

        Args:
            image_path: Path to the image file.

        Returns:
            Flattened feature vector as numpy array.
        """
        try:
            img = Image.open(image_path)
            # Resize to 64x64
            img = img.resize((64, 64))
            # Convert to RGB
            img = img.convert("RGB")
            img_array = np.array(img)

            # Compute color histogram (256 bins per channel)
            r_hist, _ = np.histogram(img_array[:, :, 0], bins=256, range=(0, 256))
            g_hist, _ = np.histogram(img_array[:, :, 1], bins=256, range=(0, 256))
            b_hist, _ = np.histogram(img_array[:, :, 2], bins=256, range=(0, 256))

            # Normalize histograms
            r_hist = r_hist.astype(float) / (r_hist.sum() + 1e-6)
            g_hist = g_hist.astype(float) / (g_hist.sum() + 1e-6)
            b_hist = b_hist.astype(float) / (b_hist.sum() + 1e-6)

            # Concatenate features
            features = np.concatenate([r_hist, g_hist, b_hist])
            return features
        except Exception as e:
            raise ValueError(f"Failed to extract features from image {image_path}: {str(e)}")

    def train_classification(self, classification_id: int, db, tenant_id: int) -> dict:
        """训练图像分类模型

        Args:
            classification_id: ID of the vision classification.
            db: Database session.
            tenant_id: Tenant ID for multi-tenancy.

        Returns:
            Dict with status, message, and accuracy.
        """
        from lumen_models.vision_training import VisionClassification, VisionImage

        # Validate classification_id is a positive integer
        if classification_id <= 0:
            return {"status": "error", "message": "Invalid classification_id"}

        # Get all images for this classification
        images = db.query(VisionImage).filter(
            VisionImage.classification_id == classification_id,
            VisionImage.tenant_id == tenant_id
        ).all()

        if len(images) < 2:
            return {"status": "error", "message": "需要至少2张图片进行训练"}

        # Prepare training data
        features_list = []
        labels = []

        for img in images:
            if not os.path.exists(img.file_path):
                continue
            try:
                features = self._extract_features(img.file_path)
                features_list.append(features)
                labels.append(img.classification_id)
            except Exception:
                # Skip images that fail to load
                continue

        if len(features_list) < 2:
            return {"status": "error", "message": "需要至少2张有效图片进行训练"}

        X = np.array(features_list)
        y = np.array(labels)

        # Split train/test with 0.2 test size
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        # Train classifier
        classifier = LogisticRegression(max_iter=1000)
        classifier.fit(X_train, y_train)

        # Evaluate
        y_pred = classifier.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)

        # Save model
        model_path = os.path.join(self.model_dir, f"classification_{classification_id}")
        # Ensure path stays within model_dir
        if not os.path.abspath(model_path).startswith(os.path.abspath(self.model_dir)):
            return {"status": "error", "message": "Invalid model path"}

        try:
            joblib.dump({"classifier": classifier}, model_path)
        except Exception as e:
            return {"status": "error", "message": f"Failed to save model: {str(e)}"}

        return {
            "status": "success",
            "model_path": model_path,
            "accuracy": accuracy,
            "message": f"训练完成，准确率: {accuracy:.2%}"
        }

    def predict(self, image_path: str, classification_id: int, tenant_id: int) -> dict:
        """预测图像分类

        Args:
            image_path: Path to the image file.
            classification_id: ID of the vision classification.
            tenant_id: Tenant ID for multi-tenancy.

        Returns:
            Dict with predicted_class_id and confidence.
        """
        # Validate classification_id is a positive integer
        if classification_id <= 0:
            return {"error": "Invalid classification_id"}

        # Validate image path
        if not os.path.exists(image_path):
            return {"error": "图片路径不存在"}

        model_path = os.path.join(self.model_dir, f"classification_{classification_id}")
        # Ensure path stays within model_dir
        if not os.path.abspath(model_path).startswith(os.path.abspath(self.model_dir)):
            return {"error": "Invalid model path"}

        if not os.path.exists(model_path):
            return {"error": "模型未训练，请先训练"}

        try:
            model_data = joblib.load(model_path)
        except Exception as e:
            return {"error": f"Failed to load model: {str(e)}"}

        classifier = model_data["classifier"]

        # Extract features from image
        try:
            features = self._extract_features(image_path)
        except Exception as e:
            return {"error": f"Failed to extract features: {str(e)}"}

        # Reshape for single sample
        X = features.reshape(1, -1)

        # Predict
        prediction = classifier.predict(X)
        probabilities = classifier.predict_proba(X)[0]

        return {
            "predicted_class_id": int(prediction[0]),
            "confidence": float(max(probabilities))
        }
