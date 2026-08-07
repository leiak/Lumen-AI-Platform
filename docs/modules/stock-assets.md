# 模块:股票素材库

> Lumen AI Platform 的公共素材库(M36.2.1 ship)。
> 文档讲透股票素材是什么、怎么用、和图片生成的区别。

---

## 1. 产品定位

**股票素材库是什么?**
- 平台预置的 30 张公共图片
- 租户共享,不用自己上传
- 用于视频合成、营销配图

**和"用户上传图片"比有什么不同?**
- 平台预置,质量保证
- 公共可见,所有租户用
- 不用占用户存储

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| 平台预置 | 30 张高质量图 |
| 全局可见 | 所有租户共享 |
| 标签分类 | nature / city / people / ... |
| 视频合成选 | 视频 ComposeModal 集成 |
| 缩略图 | 自动生成 |

---

## 3. 数据模型

### 3.1 stock_assets
```python
class StockAsset(Base):
    id: int
    name: str
    description: str
    file_path: str                # 平台预置路径
    thumbnail_path: str
    category: str                 # nature / city / people / business / ...
    tags: list
    file_size: int
    width: int
    height: int
    is_active: bool
    # tenant_id IS NULL(平台全局)
    created_at
```

### 3.2 文件
- ORM: `backend/lumen_models/stock.py`
- Schema: `backend/lumen_schemas/stock.py`
- 服务: `backend/lumen_services/stock_service.py`
- 路由: `backend/lumen_api/v1/stock.py`
- 种子: `backend/lumen_scripts/seed_stock_assets.py`

---

## 4. 30 张预置图

### 4.1 分类
- **nature**(10): 山 / 海 / 森林 / 草原 / 沙漠 / ...
- **city**(8): 城市天际线 / 街道 / 夜景 / ...
- **people**(6): 商务人士 / 团队 / 演讲 / ...
- **business**(6): 会议室 / 办公室 / 笔记本 / ...

### 4.2 来源
- 平台自有 / CC0 协议
- 不侵犯版权
- 高质量(1920x1080+)

### 4.3 位置
- `storage/stock_assets/`(git ignore,实际部署时)
- 或 `lumen-platform/stock/`(Docker volume)

---

## 5. UI

### 5.1 选择 Modal
- 文件: `frontend/components/video/StockPickerModal.tsx`
- 在视频合成 / 图片生成时弹出
- 网格:缩略图 + 名字
- 操作:选 → 加到列表

### 5.2 缩略图
- StockThumb 组件
- Bearer 模式:fetch + blob + createObjectURL
- 详见 [llm-call-logs § Bearer 模式](llm-call-logs.md)

### 5.3 后台管理
- 当前: 暂未提供增删 UI
- 计划: 系统设置 → 素材管理

---

## 6. 关键能力详解

### 6.1 全局可见
- `tenant_id IS NULL` → 所有租户可读
- 详见 [multi-tenant](../architecture/04-multi-tenant.md)

### 6.2 视频合成集成
- 在 `videos.image_paths` 加 stock asset id
- 后端 `_resolve_image_to_local_path` 解析
- 详见 [video-composition](video-composition.md)

### 6.3 URL 解析
- 接受:本地路径 / 数字 id / `image-generation/<id>` / `stock-assets/<id>` URL
- 统一翻成本地绝对路径
- M36.2.1.x ship 的修复

---

## 7. 关键代码

### 7.1 列表 API
```python
# backend/lumen_api/v1/stock.py
@router.get("/", response_model=PaginatedResponse[StockAssetRead])
def list_stock_assets(
    page: int = 1,
    page_size: int = 20,
    category: str = None,
    search: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(StockAsset).filter(StockAsset.is_active == True)
    if category:
        query = query.filter(StockAsset.category == category)
    if search:
        query = query.filter(StockAsset.name.like(f"%{search}%"))
    return paginate(query, page, page_size)
```

### 7.2 路径解析
```python
# backend/lumen_services/video_compose_service.py
def _resolve_image_to_local_path(image_input: str, tenant_id: int) -> str:
    """支持:本地路径 / 数字 id / image-generation URL / stock-assets URL"""

    # 1. 已是本地路径
    if os.path.isabs(image_input) and os.path.exists(image_input):
        return image_input

    # 2. 数字 id → stock asset
    if image_input.isdigit():
        asset = get_stock_asset(int(image_input))
        return asset.file_path

    # 3. URL 形式
    if image_input.startswith("stock-assets/"):
        asset_id = int(image_input.split("/")[1])
        asset = get_stock_asset(asset_id)
        return asset.file_path

    # 4. image-generation URL
    if image_input.startswith("image-generation/"):
        img_id = int(image_input.split("/")[1])
        img = get_image_generation(img_id, tenant_id)
        return img.file_path

    raise ValueError(f"Cannot resolve image path: {image_input}")
```

---

## 8. 边界与不做

### 8.1 当前
- ✅ 30 张预置
- ✅ 全局可见
- ✅ 视频集成
- ✅ 缩略图
- ✅ URL 解析

### 8.2 不做
- ❌ 用户上传
- ❌ 租户私有素材库
- ❌ 第三方 API 集成(unsplash 等)

---

## 9. 升级路径

### 短期
- 📋 增删 UI(系统设置)
- 📋 用户上传

### 中期
- 📋 第三方 API
- 📋 智能推荐(按 video 内容)

### 长期
- 📋 AI 生成 stock
- 📋 视频素材(动态)

---

## 10. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 列表空 | 种子没跑 | 跑 seed_stock_assets |
| 视频找不到图 | 路径解析失败 | 改 ID / URL |
| 缩略图 401 | 没带 token | 改 Bearer 模式 |

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
