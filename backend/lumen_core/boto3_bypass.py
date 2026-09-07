"""Shared boto3 client config for proxy handling — env-aware (2.1 C.2).

镜像 ``lumen_core.httpx_bypass.py`` 结构,集中管理 botocore 的 proxy
策略。boto3 / botocore 不像 httpx 那样读 Windows registry(只读
``HTTPS_PROXY`` / ``HTTP_PROXY`` env),但生产 Linux K8s 集群如果
endpoint 在代理后面,需要让 botocore 自己解析 env。

**为什么显式 ``proxies={}`` 而不是省略**:botocore 默认会读
``HTTPS_PROXY`` / ``HTTP_PROXY`` env,无需特别处理。但有些内部 S3 / MinIO
endpoint 是直连(不走代理),显式设空 proxies 避免意外继承 env。

**2.1 C.2 决策表**:
- 默认 (dev / 无 proxy env):返 ``{"proxies": {}}``,强制直连。
- 设了 ``HTTPS_PROXY`` env:返 ``{}``,botocore 自己读 env 走代理。
- 强制 override:``LUMEN_FORCE_PROXY_BYPASS=1`` → 强制返 ``{"proxies": {}}``
  bypass env 直连(本地调试企业代理但要直连 MinIO 时用)。

``S3_BYPASS_PROXY`` 单独环境变量在 ``S3Backend._bypass_proxy_kwargs`` 走,
按 S3 端点维度细粒度控制(默认 true)。本 helper 是"全局 boto3 通用"策略,
如果有 boto3 在非 S3 场景用(目前没有)再走这个。

Spec: docs-internal/superpowers/specs/2026-09-07-lumen-2.1-spec.md §Phase 0 C.2
"""
from __future__ import annotations

import os
from typing import Any, Dict


def _should_bypass_boto3_proxy() -> bool:
    """决策逻辑镜像 ``_should_bypass_proxy``,给 boto3 客户端用。"""
    force = os.getenv("LUMEN_FORCE_PROXY_BYPASS", "").strip().lower()
    if force in {"1", "true", "yes", "on"}:
        return True
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        if os.getenv(var):
            return False
    return True


def boto3_bypass_proxy_kwargs() -> Dict[str, Any]:
    """Return kwargs for ``botocore.config.Config(proxies=...)`` 决定 boto3
    是否走代理。

    决策表:
    - bypass (dev 默认) → ``{"proxies": {}}`` :禁掉任何代理。
    - 不 bypass(生产设了 HTTPS_PROXY)→ ``{}``:不传 proxies,botocore 自己读 env。
    """
    if _should_bypass_boto3_proxy():
        return {"proxies": {}}
    return {}