"""M37.2 seed: 探测 dev DB 默认 chat / embedding 模型 → 写入 system_configs。

**目的**:当用户启动评测但不指定 ``judge_model_config_id`` /
``embedding_model_config_id`` 时,API 从 ``system_configs`` 读这条默认
配置兜底。运营在 UI 改默认模型后,重跑本脚本可刷新;或者直接 UPDATE
``system_configs.value``(JSON 列,改字段不破坏 schema)。

**为什么 pymysql 直连**(M29 lesson):model_configs 表简单 SELECT,无
需 ORM mapper 上下文;直连避免 SQLAlchemy mapper 注册顺序问题。

**为什么存 system_configs 而不是文件**:运营可在 dashboard 系统设置页
改默认值,改完 UI 立即生效;不需要改代码 + 重启。

**为什么还要顶层常量**:脚本 ship 时 CI 跑一次,把 dev DB 当前状态
「快照」写进常量。开发新功能时 import 这个常量能一眼看出「上次 seed
的时候 dev DB 长这样」,避免奇怪行为(比如 dev DB 已经改了默认模型,
但代码里 hardcode 旧 ID)。

**找不到 is_default=1 行 → fall back** ``ORDER BY id LIMIT 1``(plan §T12),
warn log,绝不 raise —— ship 时 dev DB 状态未知,fallback 保证脚本
能完成。

Usage:
    cd backend && python -m lumen_scripts.seed_m37_default_eval_config

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.2
Plan: docs-internal/superpowers/plans/m37-plan.md CP4 T12
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# pymysql 第三方库无 type stubs,seed 脚本(M35/migrate_*)历来用裸 import,
# mypy 配置大概率是项目级 ignore。这里也加 type: ignore 保持一致。
import pymysql  # type: ignore[import-untyped]  # noqa: E402

from lumen_core.config import settings  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# ---------------------------------------------------------------------------
# 顶层常量 —— dev DB 探测的「snapshot」,重跑本脚本时会覆盖。
# 这些值同时写到 system_configs.eval_default_config(JSON)。
# ---------------------------------------------------------------------------

# M37.2 ship 时 dev DB 默认 chat 模型 ID(is_chat=1 AND is_default=1 优先,
# fallback ORDER BY id LIMIT 1)。脚本运行后会更新为探测值。
DEFAULT_JUDGE_MODEL_CONFIG_ID: Optional[int] = None

# 评测时也要 embedding 模型(检索用),跟 chat judge 同探测方式
DEFAULT_EMBEDDING_MODEL_CONFIG_ID: Optional[int] = None

# 默认评测 config 模板 —— 跟 M28 KB search_weights 默认值一致
# (title 10, important_kw 30, question_kw 20, text 2),这样新启动的
# eval_run 不指定 config 时,跟 production KB 检索行为一致,评测结果
# 反映生产环境。
DEFAULT_EVAL_CONFIG: Dict[str, Any] = {
    "name": "default",
    "search_weights": {
        "title": 10.0,
        "important_kw": 30.0,
        "question_kw": 20.0,
        "text": 2.0,
    },
    "top_k": 10,
    "rerank": True,
    "rerank_top_n": 5,
    "embedding_model_config_id": None,  # 由 main() 探测填入
    "judge_model_config_id": None,  # 由 main() 探测填入
    "chunking_strategy": None,
    "judge_metrics": ["faithfulness", "answer_relevancy"],
}

# system_configs 表的 key —— 全平台唯一,API 通过此 key 读默认 config
SYSTEM_CONFIG_KEY = "eval_default_config"


# ---------------------------------------------------------------------------
# pymysql 直连 dev DB(M29 经验:避免 ORM mapper 顺序问题,纯 SELECT 用 pymysql)
# ---------------------------------------------------------------------------

def _connect_dev_db() -> pymysql.connections.Connection:
    """从 settings.DATABASE_URL 解析 host / port / user / password / db。

    项目用 mysql+pymysql://root:rootpassword@localhost:3307/ai_platform
    格式,这里简单正则拆,比引入 sqlalchemy 轻。
    """
    from urllib.parse import urlparse

    url = settings.DATABASE_URL
    # urlparse 不识别 mysql+pymysql scheme,先剥 driver
    if "://" in url:
        scheme_rest = url.split("://", 1)[1]
    else:
        raise ValueError(f"DATABASE_URL 格式异常: {url}")
    # 拆 user:pass@host:port/db
    if "@" in scheme_rest:
        creds, host_db = scheme_rest.split("@", 1)
        user, password = creds.split(":", 1) if ":" in creds else (creds, "")
    else:
        user = "root"
        password = ""
        host_db = scheme_rest
    if "/" in host_db:
        host_port, db = host_db.split("/", 1)
    else:
        host_port, db = host_db, ""
    if ":" in host_port:
        host_str, port_str = host_port.split(":", 1)
        host = host_str
        port = int(port_str)
    else:
        host = host_port
        port = 3306

    logger.info("Connecting to dev DB %s:%s/%s ...", host, port, db)
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=db,
        connect_timeout=5,
    )


def _detect_default_model(
    conn: pymysql.connections.Connection,
    *,
    is_chat: Optional[bool] = None,
    is_embedding: Optional[bool] = None,
    label: str,
) -> Optional[int]:
    """探测「最合适的默认 model_config.id」。

    Args:
        conn: pymysql 连接。
        is_chat: 筛 is_chat=1;不传 = 不筛 chat 列。
        is_embedding: 筛 is_embedding=1;不传 = 不筛 embedding 列。
        label: 日志前缀("judge" / "embedding"),让 warn 信息可读。

    Returns:
        model_config.id;完全没找到 → None(交给 main() 决定怎么处理)。

    查询策略(plan §T12):
        1. WHERE is_active=1 AND (is_chat / is_embedding 过滤) AND is_default=1
        2. 找不到 → ORDER BY id ASC LIMIT 1
        3. 还找不到 → None
    """
    conditions = ["is_active = 1"]
    params: list = []
    if is_chat is not None:
        conditions.append("is_chat = %s")
        params.append(int(is_chat))
    if is_embedding is not None:
        conditions.append("is_embedding = %s")
        params.append(int(is_embedding))
    where_clause = " AND ".join(conditions)

    with conn.cursor() as cur:
        # Step 1:找 is_default=1
        cur.execute(
            f"SELECT id, name, model_type FROM model_configs "
            f"WHERE {where_clause} AND is_default = 1 "
            f"ORDER BY id ASC LIMIT 1",
            params,
        )
        row = cur.fetchone()
        if row:
            logger.info(
                "  %s default model: id=%s name=%r type=%s (is_default=1)",
                label, row[0], row[1], row[2],
            )
            return int(row[0])

        # Step 2:fallback ORDER BY id
        cur.execute(
            f"SELECT id, name, model_type FROM model_configs "
            f"WHERE {where_clause} "
            f"ORDER BY id ASC LIMIT 1",
            params,
        )
        row = cur.fetchone()
        if row:
            logger.warning(
                "  %s default model: NO is_default=1 row found, "
                "fallback to ORDER BY id LIMIT 1 → id=%s name=%r type=%s",
                label, row[0], row[1], row[2],
            )
            return int(row[0])

        # Step 3:什么都没找到
        logger.error(
            "  %s default model: no active model_configs row at all "
            "(is_active=1 + chat/embedding filter)", label,
        )
        return None


def _upsert_system_config(conn: pymysql.connections.Connection, value: Dict[str, Any]) -> None:
    """INSERT ... ON DUPLICATE KEY UPDATE 写 system_configs(zero-ALTER)。"""
    value_json = json.dumps(value, ensure_ascii=False, sort_keys=True)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO system_configs (`key`, `value`, created_at, updated_at) "
            "VALUES (%s, %s, NOW(), NOW()) "
            "ON DUPLICATE KEY UPDATE `value` = VALUES(`value`), updated_at = NOW()",
            (SYSTEM_CONFIG_KEY, value_json),
        )
    conn.commit()
    logger.info("  system_configs[%s] upserted", SYSTEM_CONFIG_KEY)


def main() -> int:
    """探测 + 写 system_configs + 更新顶层常量。

    Returns:
        0 = 成功(至少找到 chat 模型);1 = 失败(没找到任何 chat 模型)。
    """
    global DEFAULT_JUDGE_MODEL_CONFIG_ID, DEFAULT_EMBEDDING_MODEL_CONFIG_ID

    print("M37.2 seed — detecting default judge / embedding model + writing system_configs ...")
    conn = _connect_dev_db()
    try:
        judge_id = _detect_default_model(
            conn, is_chat=True, label="judge"
        )
        if judge_id is None:
            print(
                "FAILED: dev DB has no active chat model. "
                "Add one via admin UI or run seed_m35_default_models.py first."
            )
            return 1

        embedding_id = _detect_default_model(
            conn, is_embedding=True, label="embedding"
        )
        # embedding 不是硬性要求 —— 评测只用 chat judge;
        # 没 embedding 模型 → 后续检索阶段的评测会失败,但不阻塞本脚本
        if embedding_id is None:
            logger.warning(
                "No active embedding model found; eval runs without explicit "
                "embedding_model_config_id will fail at retrieval stage."
            )

        # 更新顶层常量
        DEFAULT_JUDGE_MODEL_CONFIG_ID = judge_id
        DEFAULT_EMBEDDING_MODEL_CONFIG_ID = embedding_id
        DEFAULT_EVAL_CONFIG["judge_model_config_id"] = judge_id
        DEFAULT_EVAL_CONFIG["embedding_model_config_id"] = embedding_id

        # 写 system_configs —— API 通过 key 读
        _upsert_system_config(conn, DEFAULT_EVAL_CONFIG)

        print(
            f"\nOK — written to system_configs[{SYSTEM_CONFIG_KEY!r}]:\n"
            f"  judge_model_config_id   = {judge_id}\n"
            f"  embedding_model_config_id = {embedding_id}\n"
            f"  top_k = {DEFAULT_EVAL_CONFIG['top_k']}, rerank = {DEFAULT_EVAL_CONFIG['rerank']}\n"
            f"  search_weights = {DEFAULT_EVAL_CONFIG['search_weights']}\n"
            f"  judge_metrics = {DEFAULT_EVAL_CONFIG['judge_metrics']}\n"
        )
        print(
            "Verify with:\n"
            f"  SELECT `key`, `value` FROM system_configs WHERE `key` = '{SYSTEM_CONFIG_KEY}'\n"
            f"  SELECT id, name, is_chat, is_default FROM model_configs "
            f"WHERE id IN ({judge_id}, {embedding_id or 'NULL'})"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
