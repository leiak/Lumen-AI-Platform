import os
import joblib
from typing import List
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

class NLPTrainingService:
    """NLP 训练服务"""

    def __init__(self):
        self.model_dir = "./models/nlp"
        os.makedirs(self.model_dir, exist_ok=True)

    def train_classification(self, classification_id: int, db, tenant_id: int) -> dict:
        """训练分类模型"""
        from lumen_models.nlp_training import NLPTrainingClassification, NLPAnnotation

        # Validate classification_id is a positive integer
        if classification_id <= 0:
            return {"status": "error", "message": "Invalid classification_id"}

        # 获取该分类的所有标注数据
        annotations = db.query(NLPAnnotation).filter(
            NLPAnnotation.classification_id == classification_id,
            NLPAnnotation.tenant_id == tenant_id
        ).all()

        if len(annotations) < 2:
            return {"status": "error", "message": "需要至少2条标注数据"}

        # 准备训练数据
        texts = [a.content for a in annotations]
        labels = [a.classification_id for a in annotations]

        # 分割训练/测试集
        X_train, X_test, y_train, y_test = train_test_split(
            texts, labels, test_size=0.2, random_state=42
        )

        # TF-IDF 特征提取
        vectorizer = TfidfVectorizer(max_features=1000, max_df=0.95)
        X_train_vec = vectorizer.fit_transform(X_train)
        X_test_vec = vectorizer.transform(X_test)

        # 训练分类器
        classifier = LogisticRegression(max_iter=1000)
        classifier.fit(X_train_vec, y_train)

        # 评估
        y_pred = classifier.predict(X_test_vec)
        accuracy = accuracy_score(y_test, y_pred)

        # 保存模型
        model_path = os.path.join(self.model_dir, f"classification_{classification_id}")
        # Ensure path stays within model_dir
        if not os.path.abspath(model_path).startswith(os.path.abspath(self.model_dir)):
            return {"status": "error", "message": "Invalid model path"}
        try:
            joblib.dump({"classifier": classifier, "vectorizer": vectorizer}, model_path)
        except Exception as e:
            return {"status": "error", "message": f"Failed to save model: {str(e)}"}

        return {
            "status": "success",
            "model_path": model_path,
            "accuracy": accuracy,
            "message": f"训练完成，准确率: {accuracy:.2%}"
        }

    def predict(self, text: str, classification_id: int, tenant_id: int) -> dict:
        """预测分类"""
        # Validate classification_id is a positive integer
        if classification_id <= 0:
            return {"error": "Invalid classification_id"}

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
        vectorizer = model_data["vectorizer"]

        # 特征提取
        X = vectorizer.transform([text])

        # 预测
        prediction = classifier.predict(X)
        probabilities = classifier.predict_proba(X)[0]

        return {
            "predicted_class_id": int(prediction[0]),
            "confidence": float(max(probabilities))
        }
