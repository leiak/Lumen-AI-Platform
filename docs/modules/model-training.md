# 模块:模型训练(NLP + Vision)

> Lumen AI Platform 的轻量级传统机器学习训练能力。
> 文档讲透 NLP 文本分类、Vision 图像分类、和"大模型"的分工。

---

## 1. 产品定位

**模型训练是什么?**
- 平台内置的**小模型训练**能力(scikit-learn)
- 两条线:NLP 文本分类 / Vision 图像分类
- 标注 → 训练 → 预测,全在 UI 里完成

**和"大模型"有什么不同?**

| 维度 | 大模型(LLM) | 本模块(小模型) |
|------|-------------|----------------|
| 用途 | 通用理解 / 生成 | **固定标签的分类** |
| 是否需要标注 | 不需要 | **必须标注** |
| 训练成本 | 极高(不在平台内做) | 秒级,CPU 就行 |
| 推理成本 | 每次调 API / GPU | 毫秒级,本地 |
| 可解释性 | 弱 | 强(TF-IDF 权重可看) |
| 数据出域 | 可能出域 | **完全本地** |

**业务场景?**
- 工单自动分类(退款 / 投诉 / 咨询)
- 客户意图识别,路由到不同 Agent
- 产品图片自动打标
- **数据敏感、标签固定、追求毫秒级响应**的场景

**一句话**:LLM 处理开放问题,本模块处理"这条属于哪一类"这种封闭问题 —— 又快又便宜又不出域。

---

## 2. 功能清单

| 功能 | NLP | Vision |
|------|-----|--------|
| 分类管理(CRUD) | ✅ | ✅ |
| 语料 / 图片标注 | ✅ 文本标注 | ✅ 图片上传 |
| 训练 | ✅ TF-IDF + 逻辑回归 | ✅ 颜色直方图 + 逻辑回归 |
| 准确率评估 | ✅ | ✅ |
| 在线预测 | ✅ | ✅ |
| 置信度输出 | ✅ | ✅ |
| 问答对管理 | ✅ (`nlp_qa`) | — |
| 模型持久化 | ✅ joblib | ✅ joblib |
| 多租户隔离 | ✅ | ✅ |

---

## 3. 数据模型

### 3.1 NLP 三张表

```python
# backend/lumen_models/nlp_training.py

class NLPTrainingClassification(BaseModel):
    __tablename__ = "nlp_classification"
    name: str                     # 分类名(如"退款申请")
    description: str
    keywords: list                # 关键词列表(JSON)
    tenant_id: int                # 多租户隔离
    # annotations: 一对多,cascade delete-orphan


class NLPAnnotation(BaseModel):
    __tablename__ = "nlp_annotation"
    content: str                  # 标注语料原文
    classification_id: int        # → nlp_classification.id
    tenant_id: int


class NLPQA(BaseModel):
    __tablename__ = "nlp_qa"
    question: str                 # 问题
    answer: str                   # 答案
    tenant_id: int
```

> `NLPQA` 是**独立的问答对库**,不参与分类训练,用于 FAQ 类场景。

### 3.2 Vision 两张表

```python
# backend/lumen_models/vision_training.py

class VisionClassification(BaseModel):
    __tablename__ = "vision_classification"
    name: str
    description: str
    tenant_id: int
    # images: 一对多,cascade delete-orphan


class VisionImage(BaseModel):
    __tablename__ = "vision_image"
    filename: str
    file_path: str                # 磁盘路径
    classification_id: int        # → vision_classification.id
    features: dict                # 特征向量(JSON,可缓存)
    tenant_id: int
```

### 3.3 文件清单

| 层 | NLP | Vision |
|----|-----|--------|
| ORM | `backend/lumen_models/nlp_training.py` | `backend/lumen_models/vision_training.py` |
| 服务 | `backend/lumen_services/nlp_training_service.py` | `backend/lumen_services/vision_training_service.py` |
| 路由 | `backend/lumen_api/v1/nlp.py` | `backend/lumen_api/v1/vision.py` |
| 模型加载 | `backend/lumen_services/model_loader.py` | 同左 |
| 前端 | `frontend/app/dashboard/training/nlp/` | `frontend/app/dashboard/training/vision/` |

模型文件落盘位置:

```
backend/models/nlp/classification_<id>       # joblib: {classifier, vectorizer}
backend/models/vision/classification_<id>    # joblib: {classifier}
```

---

## 4. API 清单

### 4.1 NLP(14 个端点)

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/nlp/classification/` | 分类列表(分页) |
| POST | `/api/v1/nlp/classification/` | 创建分类 |
| GET | `/api/v1/nlp/classification/{id}` | 分类详情 |
| PUT | `/api/v1/nlp/classification/{id}` | 更新分类 |
| DELETE | `/api/v1/nlp/classification/{id}` | 删除分类(级联删标注) |
| GET | `/api/v1/nlp/annotation/` | 标注列表(分页,可按分类过滤) |
| POST | `/api/v1/nlp/annotation/` | 新增标注 |
| DELETE | `/api/v1/nlp/annotation/{id}` | 删除标注 |
| GET | `/api/v1/nlp/qa/` | 问答对列表 |
| POST | `/api/v1/nlp/qa/` | 新增问答对 |
| PUT | `/api/v1/nlp/qa/{id}` | 更新问答对 |
| DELETE | `/api/v1/nlp/qa/{id}` | 删除问答对 |
| **POST** | **`/api/v1/nlp/train`** | **触发训练** |
| **POST** | **`/api/v1/nlp/predict`** | **在线预测** |

### 4.2 Vision(8 个端点)

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/vision/classification/` | 分类列表 |
| POST | `/api/v1/vision/classification/` | 创建分类 |
| DELETE | `/api/v1/vision/classification/{id}` | 删除分类(级联删图片) |
| POST | `/api/v1/vision/image/` | 上传图片(multipart) |
| GET | `/api/v1/vision/image/` | 图片列表 |
| DELETE | `/api/v1/vision/image/{id}` | 删图片 |
| **POST** | **`/api/v1/vision/train`** | **触发训练** |
| **POST** | **`/api/v1/vision/predict`** | **在线预测** |

> 全部返回 `SingleResponse[T]` / `PaginatedResponse[T]` 信封。

---

## 5. 算法详解

### 5.1 NLP:TF-IDF + 逻辑回归

```python
# backend/lumen_services/nlp_training_service.py

def train_classification(self, classification_id: int, db, tenant_id: int) -> dict:
    # 1. 取该分类下全部标注(带 tenant_id 隔离)
    annotations = db.query(NLPAnnotation).filter(
        NLPAnnotation.classification_id == classification_id,
        NLPAnnotation.tenant_id == tenant_id,
    ).all()

    if len(annotations) < 2:
        return {"status": "error", "message": "需要至少2条标注数据"}

    texts = [a.content for a in annotations]
    labels = [a.classification_id for a in annotations]

    # 2. 8:2 切分训练/测试集(random_state=42 保证可复现)
    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.2, random_state=42
    )

    # 3. TF-IDF 特征提取
    #    max_features=1000 控制维度;max_df=0.95 过滤过于常见的词
    vectorizer = TfidfVectorizer(max_features=1000, max_df=0.95)
    X_train_vec = vectorizer.fit_transform(X_train)
    X_test_vec = vectorizer.transform(X_test)

    # 4. 逻辑回归
    classifier = LogisticRegression(max_iter=1000)
    classifier.fit(X_train_vec, y_train)

    # 5. 评估
    accuracy = accuracy_score(y_test, classifier.predict(X_test_vec))

    # 6. classifier 和 vectorizer 必须一起存 —— 推理时要用同一个词表
    joblib.dump({"classifier": classifier, "vectorizer": vectorizer}, model_path)

    return {"status": "success", "accuracy": accuracy, ...}
```

**关键点**:
- `vectorizer` **必须和 classifier 一起持久化**。推理时用新 vectorizer 会得到完全不同的特征空间,预测全错。
- `max_df=0.95`:出现在 95% 以上文档里的词(的、了、是)自动过滤,相当于自适应停用词。

### 5.2 Vision:颜色直方图 + 逻辑回归

```python
def _extract_features(self, image_path: str) -> np.ndarray:
    img = Image.open(image_path)
    img = img.resize((64, 64))     # 统一尺寸,消除分辨率差异
    img = img.convert("RGB")
    arr = np.array(img)

    # RGB 三通道各 256 bin 的直方图
    r_hist, _ = np.histogram(arr[:, :, 0], bins=256, range=(0, 256))
    g_hist, _ = np.histogram(arr[:, :, 1], bins=256, range=(0, 256))
    b_hist, _ = np.histogram(arr[:, :, 2], bins=256, range=(0, 256))

    # 归一化 —— +1e-6 防止全黑图除零
    r_hist = r_hist.astype(float) / (r_hist.sum() + 1e-6)
    g_hist = g_hist.astype(float) / (g_hist.sum() + 1e-6)
    b_hist = b_hist.astype(float) / (b_hist.sum() + 1e-6)

    return np.concatenate([r_hist, g_hist, b_hist])   # 768 维
```

**特征是 768 维的颜色分布向量。**

**能力边界(必须理解)**:

颜色直方图**完全丢失空间信息**。它只知道"图里有多少红、多少蓝",不知道红色在哪、是什么形状。

| 场景 | 效果 |
|------|------|
| 区分"雪景 vs 沙漠 vs 森林" | ✅ 很好(色调差异大) |
| 区分"红色包装 vs 蓝色包装" | ✅ 很好 |
| 区分"猫 vs 狗" | ❌ 基本不行 |
| 区分"合格件 vs 有划痕的件" | ❌ 不行 |
| 区分"正着的图 vs 倒着的图" | ❌ 直方图完全相同 |

**需要形状/纹理判别时,这个模块不适用** —— 用 CNN 或视觉大模型。

### 5.3 训练流程共性

```
标注数据 (≥ 2 条)
    ↓
train_test_split(test_size=0.2, random_state=42)
    ↓
特征提取 (TF-IDF / 颜色直方图)
    ↓
LogisticRegression(max_iter=1000)
    ↓
accuracy_score 评估
    ↓
joblib.dump → backend/models/{nlp,vision}/classification_<id>
```

### 5.4 预测

```python
def predict(self, text: str, classification_id: int, tenant_id: int) -> dict:
    model_path = os.path.join(self.model_dir, f"classification_{classification_id}")
    if not os.path.exists(model_path):
        return {"error": "模型未训练，请先训练"}

    model_data = joblib.load(model_path)
    X = model_data["vectorizer"].transform([text])       # 用训练时的词表
    prediction = model_data["classifier"].predict(X)
    probabilities = model_data["classifier"].predict_proba(X)[0]

    return {
        "predicted_class_id": int(prediction[0]),
        "confidence": float(max(probabilities)),         # 最高类别的概率
    }
```

**confidence 怎么用**:

| 置信度 | 建议动作 |
|--------|----------|
| > 0.85 | 自动执行 |
| 0.6 ~ 0.85 | 执行但标记待复核 |
| < 0.6 | 转人工 / 回落到 LLM |

---

## 6. 安全设计

服务层对**路径穿越**做了显式防护:

```python
model_path = os.path.join(self.model_dir, f"classification_{classification_id}")

# 防止 classification_id 被构造成 "../../etc/passwd" 之类
if not os.path.abspath(model_path).startswith(os.path.abspath(self.model_dir)):
    return {"status": "error", "message": "Invalid model path"}
```

同时校验 `classification_id > 0`。

**图片加载失败会 skip 而不是整体失败**:

```python
for img in images:
    if not os.path.exists(img.file_path):
        continue                     # 文件丢了,跳过这一张
    try:
        features = self._extract_features(img.file_path)
        ...
    except Exception:
        continue                     # 解析失败,跳过
```

这样单张坏图不会让整次训练报废。但代价是**训练集悄悄变小** —— 训练后要核对 accuracy 是否异常。

---

## 7. UI

### 7.1 NLP 训练页

- 路径: `frontend/app/dashboard/training/nlp/`
- 三个 Tab:
  1. **分类管理** — 分类列表 + 关键词
  2. **语料标注** — 输入文本 → 选分类 → 保存
  3. **问答对** — question / answer 成对管理
- 操作按钮:「训练」→ 调 `/nlp/train`,弹出准确率
- 「测试」输入框:输入一段文字 → 调 `/nlp/predict` → 显示预测分类 + 置信度

### 7.2 Vision 训练页

- 路径: `frontend/app/dashboard/training/vision/`
- 分类管理 + 图片上传(拖拽)
- 图片网格展示(缩略图走 [Bearer 模式](../troubleshooting/common-errors.md#21-img-src-加载受保护资源必-401))
- 「训练」+「测试」(上传一张图预测)

---

## 8. 典型使用流程

```
1. 建分类
   POST /nlp/classification/  {"name": "退款申请", "keywords": ["退款", "退货"]}
   POST /nlp/classification/  {"name": "产品咨询"}
   POST /nlp/classification/  {"name": "投诉建议"}

2. 标注语料(每类至少 20~50 条,越多越准)
   POST /nlp/annotation/  {"content": "我要退货", "classification_id": 1}
   POST /nlp/annotation/  {"content": "这个怎么用", "classification_id": 2}
   ...

3. 训练
   POST /nlp/train  {"classification_id": 1}
   → {"status": "success", "accuracy": 0.92, "message": "训练完成，准确率: 92.00%"}

4. 预测
   POST /nlp/predict  {"text": "买了三天就坏了要求退款"}
   → {"predicted_class_id": 1, "confidence": 0.94}

5. 接进业务
   工单进来 → predict → confidence > 0.85 自动路由到对应 Agent
                      → confidence 低 → 转人工
```

**标注量建议**:

| 标注量/类 | 预期效果 |
|-----------|----------|
| < 10 | 几乎不可用,过拟合 |
| 20~50 | 简单场景可用 |
| 100~300 | 稳定可用 |
| > 500 | 边际收益递减,考虑换模型 |

---

## 9. 与其他模块的关系

### 9.1 与 Agent
- 训练好的分类器可以作为 Agent 的**前置路由**:先分类,再决定用哪个 Agent
- 也可以包成技能,由 Agent 主动调用

### 9.2 与工作流
- 工作流的 **Question Classifier 节点**用的是 LLM 分类
- 本模块是**小模型分类** —— 更快更便宜,但需要标注
- 两者可以组合:小模型先跑,低置信度时才 fallback 到 LLM

### 9.3 与知识库
- 完全独立。KB 做的是**检索**,本模块做的是**分类**
- 但可以配合:先分类确定领域,再去对应 KB 检索

---

## 10. 边界与不做

### 10.1 当前
- ✅ NLP 文本分类(TF-IDF + LR)
- ✅ Vision 图像分类(颜色直方图 + LR)
- ✅ 准确率评估
- ✅ 在线预测 + 置信度
- ✅ 多租户隔离
- ✅ 路径穿越防护

### 10.2 不做
- ❌ 深度学习(CNN / BERT / Transformer)
- ❌ GPU 训练
- ❌ 目标检测 / 分割(只做整图分类)
- ❌ 序列标注(NER)
- ❌ 大模型微调(LoRA / 全参)
- ❌ 训练任务异步化(当前是同步阻塞请求)
- ❌ 模型版本管理 / 回滚
- ❌ 混淆矩阵 / P-R 曲线等详细指标(只给 accuracy)
- ❌ 交叉验证(单次 8:2 切分)

### 10.3 已知局限

| 局限 | 影响 | 缓解 |
|------|------|------|
| 训练同步执行 | 数据量大时请求超时 | 控制标注量,或改 Celery 异步 |
| 只输出 accuracy | 类别不平衡时具误导性 | 保持各类标注量均衡 |
| 单次切分不交叉验证 | 小数据集上 accuracy 波动大 | 多看几次,别只信一个数 |
| 颜色直方图丢空间信息 | 形状类任务完全无效 | 换 CNN |
| 模型存本地磁盘 | 多实例部署时不共享 | 单实例,或挂共享存储 |

---

## 11. 升级路径

### 短期
- 📋 训练异步化(Celery + 进度推送)
- 📋 混淆矩阵 / per-class P/R/F1
- 📋 交叉验证(K-fold)
- 📋 标注数据导入 / 导出(CSV)

### 中期
- 📋 NLP 换 embedding 特征(复用平台已有的 embedding 模型,替代 TF-IDF)
- 📋 Vision 换预训练 CNN 特征(ResNet / CLIP 抽特征 + LR 分类)
- 📋 主动学习(挑最不确定的样本让人标)
- 📋 模型版本管理 + A/B

### 长期
- 📋 LoRA 微调
- 📋 目标检测 / OCR 训练
- 📋 自动超参搜索

---

## 12. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| `需要至少2条标注数据` | 标注太少 | 补标注 |
| `模型未训练，请先训练` | 没跑过 train | 先训练 |
| accuracy 异常低 | 类别混淆 / 标注错 | 检查标注一致性 |
| accuracy = 1.0 | 数据太少,过拟合 | 加数据,别信这个数 |
| accuracy 忽高忽低 | 单次切分 + 小数据集 | 加数据 |
| Vision 训练后预测全错 | 颜色直方图不适合该任务 | 换方法(见 §5.2) |
| `需要至少2张有效图片` | 图片文件丢了被 skip | 查 `file_path` 是否存在 |
| `Failed to save model` | `models/` 目录权限 | 检查目录可写 |
| `Invalid model path` | classification_id 异常 | 检查传参 |
| 训练请求超时 | 同步训练 + 数据量大 | 减数据 / 上异步 |
| 换实例后模型没了 | 模型存本地磁盘 | 挂共享存储 |

---

**相关文档**
- [模型管理](model-management.md) — 大模型配置(和本模块不是一回事)
- [Agent](agent.md)
- [工作流节点 § Question Classifier](workflow-nodes.md)
- [多租户隔离](../architecture/04-multi-tenant.md)

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
