"""Phase 1 Group A 2.3 (2026-09-03): CircuitBreaker — 自写轻量级熔断器。

**为什么需要**: Phase 0 ship 了限流(fail-closed)+ dist_lock + idempotency,
但客户端故障(ollama 502 / OpenAI 5xx / MinIO down)会直接穿透到业务层,
每次都等 tenacity 3 次 timeout 累积 ~1.5s 后才 fail-fast。熔断器在连续故障
N 次后**主动拒绝**,让业务层立即拿到 CircuitOpenError,降级走 fallback
(Phase 1 2.4 @degradable 装饰器接住),避免故障期间的雪崩。

**三态模型**(标准熔断器,Nygard 经典版):

    closed  --N 次失败-->  open
    open    --recovery_timeout 后-->  half_open
    half_open --K 次连续成功-->  closed
    half_open --任一失败-->  open (重置 timer)

- **closed**: 正常调用,失败累加 failure_count;达到 failure_threshold → open。
- **open**: 拒绝所有调用,直接抛 ``CircuitOpenError``,不走函数体。
- **half_open**: 放行少量调用试探,任一失败立即回 open,连续 success_count
  达到 half_open_max 才回 closed(避免下游刚恢复又被打挂)。

**为什么不引第三方库**: pybreaker / circuitbreaker 都是 5+ 年没大更的小库,
新增依赖带来的是学习成本而不是功能(我们的需求就 Nygard 三态),且跟项目
lumen_* 命名一致,完全可控。Phase 1 Group A 决策 §2.3 选 A。

**Prometheus**: ``lumen_circuit_breaker_state{name, state}`` Gauge,
closed=0 / half_open=1 / open=2。每次状态切换更新 gauge,跟 Phase 0
metrics 模块协同。

**配置**:
- ollama: failure_threshold=5 / recovery_timeout=30s / half_open_max=3
- openai: failure_threshold=10 / recovery_timeout=60s / half_open_max=3
- elasticsearch: failure_threshold=5 / recovery_timeout=20s / half_open_max=3
- s3: failure_threshold=3 / recovery_timeout=10s / half_open_max=2
- mcp: failure_threshold=5 / recovery_timeout=30s / half_open_max=3
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)


# 状态码(Prometheus gauge value)
STATE_CLOSED = 0
STATE_HALF_OPEN = 1
STATE_OPEN = 2


# 默认配置:业务 override 用 BREAKERS dict
DEFAULT_BREAKER_CONFIGS: Dict[str, Dict[str, int]] = {
    "ollama": {"failure_threshold": 5, "recovery_timeout": 30, "half_open_max": 3},
    "openai": {"failure_threshold": 10, "recovery_timeout": 60, "half_open_max": 3},
    "elasticsearch": {"failure_threshold": 5, "recovery_timeout": 20, "half_open_max": 3},
    "s3": {"failure_threshold": 3, "recovery_timeout": 10, "half_open_max": 2},
    "mcp": {"failure_threshold": 5, "recovery_timeout": 30, "half_open_max": 3},
}


class CircuitOpenError(Exception):
    """熔断器开启,拒绝调用。caller 应走 fallback,不重试。"""


class CircuitBreaker:
    """三态熔断器,单实例对应一个被保护资源(ollama / openai / s3 / ...)。"""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        half_open_max: int = 3,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max
        self.state = "closed"
        self.failure_count = 0
        self.success_count = 0  # half_open 阶段累加
        self.opened_at = 0.0  # monotonic time when transitioned to open

    def _set_state(self, new_state: str) -> None:
        """切换状态 + 更新 Prometheus gauge。"""
        if new_state == self.state:
            return
        old = self.state
        self.state = new_state
        logger.info(
            "circuit_breaker[%s]: %s -> %s (failure_count=%d, success_count=%d)",
            self.name, old, new_state, self.failure_count, self.success_count,
        )
        # Prometheus 状态上报(模块级 try/except 防 metrics 故障影响 breaker)
        try:
            from lumen_core.metrics import lumen_circuit_breaker_state
            for st_name, st_code in (
                ("closed", STATE_CLOSED),
                ("half_open", STATE_HALF_OPEN),
                ("open", STATE_OPEN),
            ):
                # 用 labels(name=..., state=...) 设置当前态 = 1,其他 = 0
                lumen_circuit_breaker_state.labels(
                    breaker=self.name, state=st_name,
                ).set(1 if st_name == new_state else 0)
            del st_code  # silence lint
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "circuit_breaker[%s]: failed to update Prometheus gauge: %s",
                self.name, e,
            )

    def _on_success(self) -> None:
        if self.state == "half_open":
            self.success_count += 1
            if self.success_count >= self.half_open_max:
                self.failure_count = 0
                self.success_count = 0
                self._set_state("closed")
        else:
            # closed: 重置失败计数(避免偶发失败累加误触)
            self.failure_count = 0

    def _on_failure(self) -> None:
        if self.state == "half_open":
            # half_open 任一失败立即回 open + 重置 timer
            self.success_count = 0
            self.opened_at = time.monotonic()
            self._set_state("open")
            return
        # closed: 累加
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.opened_at = time.monotonic()
            self._set_state("open")

    def _allow_request(self) -> bool:
        """检查是否允许调用。open + 未到 recovery_timeout → False。"""
        if self.state == "open":
            if time.monotonic() - self.opened_at >= self.recovery_timeout:
                self.success_count = 0
                self._set_state("half_open")
                return True
            return False
        return True

    async def call_async(self, coro_factory: Callable[[], Awaitable[Any]]) -> Any:
        """async 调用入口。coro_factory 返回新的 coroutine(避免已 await 的重用)。"""
        if not self._allow_request():
            raise CircuitOpenError(
                f"circuit_breaker[{self.name}] is OPEN; refusing call"
            )
        try:
            result = await coro_factory()
        except Exception:
            self._on_failure()
            raise
        else:
            self._on_success()
            return result

    def call_sync(self, func: Callable[[], Any]) -> Any:
        """sync 调用入口。"""
        if not self._allow_request():
            raise CircuitOpenError(
                f"circuit_breaker[{self.name}] is OPEN; refusing call"
            )
        try:
            result = func()
        except Exception:
            self._on_failure()
            raise
        else:
            self._on_success()
            return result

    def force_open(self) -> None:
        """手动开启(测试 / 运维用)。"""
        self.opened_at = time.monotonic()
        self._set_state("open")

    def force_close(self) -> None:
        """手动关闭(测试 / 运维用)。"""
        self.failure_count = 0
        self.success_count = 0
        self._set_state("closed")


class CircuitBreakerRegistry:
    """进程内 breaker 单例 registry,按 name 共享 instance。

    测试时通过 ``reset_all()`` 清空 registry,避免跨测试污染。
    """

    _breakers: Dict[str, CircuitBreaker] = {}

    @classmethod
    def get(cls, name: str, **kwargs: Any) -> CircuitBreaker:
        if name not in cls._breakers:
            cfg = DEFAULT_BREAKER_CONFIGS.get(name, {})
            merged = {**cfg, **kwargs}
            cls._breakers[name] = CircuitBreaker(name=name, **merged)
        return cls._breakers[name]

    @classmethod
    def reset_all(cls) -> None:
        """测试 fixture 用,清空 registry。"""
        cls._breakers.clear()

    @classmethod
    def get_all(cls) -> Dict[str, CircuitBreaker]:
        """admin endpoint / metrics dump 用。"""
        return dict(cls._breakers)


__all__ = [
    "CircuitOpenError",
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "STATE_CLOSED",
    "STATE_HALF_OPEN",
    "STATE_OPEN",
    "DEFAULT_BREAKER_CONFIGS",
]
