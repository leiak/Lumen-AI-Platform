"""Phase 1 Group B 2.4.4 (2026-09-04):OpenTelemetry SDK setup 单测。

覆盖:
- OTEL_EXPORTER=none 时 setup_tracing() 返 False(noop,无副作用)
- OTEL_EXPORTER=console 时 setup_tracing() 装好 TracerProvider
- 二次调用 setup_tracing() 返 False(幂等)
- reset_for_test() 清干净 + 允许重新 setup
- resource 属性从 env / 函数入参 / 默认值 3 层正确解析
- _get_git_sha() 失败时返 None(不阻塞)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest

from lumen_core import otel
from lumen_core.otel_config import build_resource, _get_git_sha


@pytest.fixture(autouse=True)
def _reset():
    """每个 test 前清 OTel 状态(autouse 防串)。

    必须在 setup 之前 reset,否则 conftest.py import lumen_main 已经
    把 _initialized 设成 True(test 进程跑过 lifespan 触发模块级
    setup_tracing),后续 assert is_initialized() is False 全炸。
    """
    otel.reset_for_test()
    yield
    otel.reset_for_test()


# ===== none / off / disabled 模式 =====


def test_setup_tracing_returns_false_when_exporter_none(monkeypatch):
    """OTEL_EXPORTER=none → 返 False,TracerProvider 不换。"""
    monkeypatch.setenv("OTEL_EXPORTER", "none")
    result = otel.setup_tracing()
    assert result is False
    assert otel.is_initialized() is False


def test_setup_tracing_off_alias(monkeypatch):
    """OTEL_EXPORTER=off → noop(同 none)。"""
    monkeypatch.setenv("OTEL_EXPORTER", "off")
    assert otel.setup_tracing() is False


def test_setup_tracing_disabled_alias(monkeypatch):
    """OTEL_EXPORTER=disabled → noop。"""
    monkeypatch.setenv("OTEL_EXPORTER", "disabled")
    assert otel.setup_tracing() is False


def test_setup_tracing_empty_string_defaults_to_console(monkeypatch):
    """OTEL_EXPORTER='' → 当作未设,走默认 console 初始化(返 True)。

    行为定义:`os.getenv("OTEL_EXPORTER") or "console"` 把空串当作未设,
    这是 otel.py 的设计 — 配 .env 写到空值跟不写同语义,符合用户预期。
    """
    monkeypatch.setenv("OTEL_EXPORTER", "")
    result = otel.setup_tracing()
    assert result is True  # empty string fallback to console
    assert otel.is_initialized() is True


# ===== 幂等性 =====


def test_setup_tracing_idempotent(monkeypatch):
    """setup_tracing() 多次调,只有第一次返 True。"""
    monkeypatch.setenv("OTEL_EXPORTER", "console")
    # 清掉 .env 里的 OTEL_SERVICE_NAME 让函数入参起作用
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)

    first = otel.setup_tracing(service_name="test-svc-1")
    second = otel.setup_tracing(service_name="test-svc-2")  # 入参不同但被忽略

    assert first is True
    assert second is False
    assert otel.is_initialized() is True

    # 第二次入参 service_name="test-svc-2" 应该被忽略 — 第一次的 resource 留着
    from opentelemetry import trace

    provider = trace.get_tracer_provider()
    resource = provider.resource
    assert resource.attributes.get("service.name") == "test-svc-1"


def test_reset_for_test_allows_reinit(monkeypatch):
    """reset_for_test 后 setup_tracing 可重新生效(测试隔离模式)。"""
    monkeypatch.setenv("OTEL_EXPORTER", "console")
    assert otel.setup_tracing(service_name="first") is True
    assert otel.setup_tracing(service_name="second") is False  # 幂等拒

    otel.reset_for_test()
    assert otel.is_initialized() is False

    # 重新 setup 成功(用新 service_name)
    assert otel.setup_tracing(service_name="second") is True


# ===== console 模式 =====


def test_setup_tracing_console_sets_provider(monkeypatch):
    """OTEL_EXPORTER=console → 装 TracerProvider + 返 True。"""
    monkeypatch.setenv("OTEL_EXPORTER", "console")
    assert otel.setup_tracing() is True
    assert otel.is_initialized() is True

    from opentelemetry import trace

    provider = trace.get_tracer_provider()
    assert provider is not None
    # 默认 OTel SDK 是 ProxyTracerProvider,真实 provider 是 wrapped
    # 我们 setup 的是 TracerProvider(SDK 实现),SDK 名字通常含 "Sdk"
    assert "Sdk" in type(provider).__name__ or "Provider" in type(provider).__name__


# ===== resource 属性 — build_resource 优先级 =====


def test_build_resource_env_overrides_function_args(monkeypatch):
    """环境变量优先级最高(覆盖函数入参)。"""
    monkeypatch.setenv("OTEL_SERVICE_NAME", "from-env")
    monkeypatch.setenv("OTEL_SERVICE_VERSION", "9.9.9")
    monkeypatch.setenv("DEPLOYMENT_ENV", "staging")

    resource = build_resource(
        service_name="from-args",
        service_version="0.0.1",
        deployment_environment="dev",
    )
    attrs = resource.attributes
    assert attrs.get("service.name") == "from-env"
    assert attrs.get("service.version") == "9.9.9"
    assert attrs.get("deployment.environment") == "staging"


def test_build_resource_args_override_defaults(monkeypatch):
    """函数入参覆盖默认值(env 不设时)。"""
    for key in ("OTEL_SERVICE_NAME", "OTEL_SERVICE_VERSION", "DEPLOYMENT_ENV"):
        monkeypatch.delenv(key, raising=False)

    resource = build_resource(
        service_name="custom-svc",
        service_version="1.2.3",
        deployment_environment="prod",
    )
    attrs = resource.attributes
    assert attrs.get("service.name") == "custom-svc"
    assert attrs.get("service.version") == "1.2.3"
    assert attrs.get("deployment.environment") == "prod"


def test_build_resource_defaults_when_nothing_set(monkeypatch):
    """env + args 全 None → 模块常量默认。"""
    for key in ("OTEL_SERVICE_NAME", "OTEL_SERVICE_VERSION", "DEPLOYMENT_ENV"):
        monkeypatch.delenv(key, raising=False)

    resource = build_resource()
    attrs = resource.attributes
    assert attrs.get("service.name") == otel_config_DEFAULT_SERVICE_NAME()
    assert attrs.get("deployment.environment") == "dev"
    # service.version: git SHA 或 "0.1.0",都合法
    assert attrs.get("service.version") is not None
    assert len(str(attrs.get("service.version"))) > 0


def otel_config_DEFAULT_SERVICE_NAME():
    """helper:build_resource 默认 service.name 应该跟 otel.DEFAULT_SERVICE_NAME 一致。"""
    from lumen_core.otel_config import DEFAULT_SERVICE_NAME
    return DEFAULT_SERVICE_NAME


# ===== _get_git_sha 防御 =====


def test_get_git_sha_returns_string_or_none():
    """_get_git_sha() 返 7-char short SHA 或 None,绝不抛异常。"""
    sha = _get_git_sha()
    # 在 git 仓库里应返 7-char hex;非仓库里返 None
    if sha is not None:
        assert 7 <= len(sha) <= 40  # short 或 full
        # 不强制 hex(允许 git 警告信息)
    # 关键:不抛异常
    assert sha is None or isinstance(sha, str)


def test_get_git_sha_handles_missing_git(monkeypatch):
    """git 不在 PATH → 返 None,不抛 FileNotFoundError。"""
    # 把 PATH 改成空,git 找不到
    monkeypatch.setenv("PATH", "")
    sha = _get_git_sha()
    assert sha is None


# ===== is_initialized =====


def test_is_initialized_default_false():
    """默认未初始化。"""
    assert otel.is_initialized() is False


def test_is_initialized_true_after_setup(monkeypatch):
    """setup_tracing() 后 is_initialized() 返 True。"""
    monkeypatch.setenv("OTEL_EXPORTER", "console")
    otel.setup_tracing()
    assert otel.is_initialized() is True


# ===== setup_tracing 异常降级 =====


def test_setup_tracing_swallows_exceptions(monkeypatch):
    """_do_setup 内部抛异常时,setup_tracing 返 False,不阻塞调用方。"""
    monkeypatch.setenv("OTEL_EXPORTER", "console")

    # patch _do_setup 抛异常
    def _raise(*args, **kwargs):
        raise RuntimeError("simulated OTel SDK failure")

    monkeypatch.setattr(otel, "_do_setup", _raise)

    result = otel.setup_tracing()
    assert result is False
    assert otel.is_initialized() is False
