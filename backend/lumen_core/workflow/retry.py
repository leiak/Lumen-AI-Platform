"""P2 共享重试配置 + 领域错误。"""
from pydantic import BaseModel, ConfigDict, Field


class RetryConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    max_retries: int = Field(default=0, ge=0, le=10)
    retry_interval: float = Field(default=1.0, ge=0.0)
    retry_on: list[str] | None = None  # P2 留口,默认 None = 重试全部异常


class NodeRunError(Exception):
    """P2 引入。节点失败且 error_strategy 阻止继续推进时抛出。

    由 WorkflowExecutor._execute_node_with_handling 捕获,记录到
    WorkflowNodeRun.error_message,然后停止该分支路由。
    """
    pass
