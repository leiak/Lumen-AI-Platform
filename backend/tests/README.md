# Lumen AI Platform 测试文档

## 测试结构

```
tests/
├── conftest.py              # pytest 配置
├── unit/                    # 单元测试
│   ├── test_chunking_service.py    # 分块服务测试
│   ├── test_logging_service.py     # 日志服务测试
│   └── test_workflow_executor.py   # 工作流执行器测试
└── integration/            # 集成测试
    └── test_workflow_api.py        # 工作流 API 测试
```

## 运行测试

### 前置条件

```bash
cd backend
pip install pytest pytest-asyncio
```

### 运行所有测试

```bash
cd backend
pytest
```

### 运行单元测试

```bash
pytest tests/unit/
```

### 运行集成测试

```bash
pytest tests/integration/
```

### 运行特定测试文件

```bash
pytest tests/unit/test_chunking_service.py -v
```

### 运行特定测试用例

```bash
pytest tests/unit/test_chunking_service.py::TestSemanticChunking::test_chinese_text -v
```

## 测试覆盖模块

| 模块 | 测试文件 | 说明 |
|------|----------|------|
| 分块服务 | test_chunking_service.py | 测试 FixedSize/Semantic/DocumentStructure 分块 |
| 日志服务 | test_logging_service.py | 测试审计日志、操作日志、查询日志 |
| 工作流执行器 | test_workflow_executor.py | 测试工作流节点执行、调度器 |
| 工作流 API | test_workflow_api.py | 测试 CRUD API 端点 |
| 知识库 API | test_workflow_api.py | 测试知识库 API |
| 日志 API | test_workflow_api.py | 测试日志查询 API |
| 认证 API | test_workflow_api.py | 测试登录和用户认证 |

## 测试配置

pytest.ini 配置文件:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

## Mock 数据库

集成测试使用 FastAPI 的 TestClient，可以不依赖真实数据库进行 API 测试。

## 添加新测试

1. 单元测试放在 `tests/unit/test_<模块名>.py`
2. 集成测试放在 `tests/integration/test_<功能名>.py`
3. 测试类以 `Test` 开头
4. 测试方法以 `test_` 开头
