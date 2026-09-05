"""Phase 1 Group B 2.4.4 (2026-09-04): OpenTelemetry Resource 构造。

``Resource`` 是 OTel SDK 的"这个进程是谁"的描述(service.name / version /
deployment.environment)。所有 span / metric / log 自动挂这些 attribute,
Jaeger / Tempo 里按 service.name 切分 trace。

**优先级**(从低到高,后写覆盖前写):
  1. 模块常量默认(DEFAULT_SERVICE_NAME / DEFAULT_DEPLOYMENT_ENV)
  2. 函数入参(service_name= / service_version= / deployment_environment=)
  3. 环境变量(OTEL_SERVICE_NAME / OTEL_SERVICE_VERSION / DEPLOYMENT_ENV)

**service.version 推断**:默认从 ``git rev-parse --short HEAD`` 拿 git
 short SHA(7 char)。CI 容器里 git 不在 / .git 不可读时返 None,fallback
 到 DEFAULT_SERVICE_VERSION。
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# backend/ 目录根(repo根的子目录)
BACKEND_ROOT = Path(__file__).resolve().parents[2]  # backend/

DEFAULT_SERVICE_NAME = "lumen-backend"
DEFAULT_SERVICE_VERSION = "0.1.0"
DEFAULT_DEPLOYMENT_ENV = "dev"


def _get_git_sha() -> Optional[str]:
    """取当前 git short SHA (7 char),用于 service.version label。

    失败时返 None — ``build_resource`` 链 fallback 到 DEFAULT_SERVICE_VERSION。
    不抛异常(避免 git 未装 / .git 不可读阻塞 uvicorn 启动)。
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(BACKEND_ROOT.parent),  # repo root(beyond backend/)
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            sha = result.stdout.strip()
            if sha:
                return sha
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        # git 未装、timeout、permission denied 等
        pass
    return None


def build_resource(
    service_name: Optional[str] = None,
    service_version: Optional[str] = None,
    deployment_environment: Optional[str] = None,
) -> "Resource":
    """Build OTel ``Resource`` with service / deployment attributes。

    Args:
        service_name: 覆盖默认 "lumen-backend"。生产环境用,例如
            "lumen-backend-prod"。
        service_version: 覆盖默认 git SHA / "0.1.0"。
        deployment_environment: 覆盖默认 "dev"。生产设 "prod" / "staging"。

    Returns:
        ``opentelemetry.sdk.resources.Resource`` 实例,可直接传给
        ``TracerProvider(resource=...)``。
    """
    from opentelemetry.sdk.resources import Resource  # local:顶层 import 重

    name = (
        os.getenv("OTEL_SERVICE_NAME")
        or service_name
        or DEFAULT_SERVICE_NAME
    )
    version = (
        os.getenv("OTEL_SERVICE_VERSION")
        or service_version
        or _get_git_sha()
        or DEFAULT_SERVICE_VERSION
    )
    env = (
        os.getenv("DEPLOYMENT_ENV")
        or deployment_environment
        or DEFAULT_DEPLOYMENT_ENV
    )

    return Resource.create(
        {
            "service.name": name,
            "service.version": version,
            "deployment.environment": env,
        }
    )


__all__ = [
    "build_resource",
    "DEFAULT_SERVICE_NAME",
    "DEFAULT_SERVICE_VERSION",
    "DEFAULT_DEPLOYMENT_ENV",
]