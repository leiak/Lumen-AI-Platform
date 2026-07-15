"""Tests for customer table migrations (idempotency).

Spec: docs/superpowers/specs/2026-06-20-customer-management-design.md §3.4
Plan: docs/superpowers/plans/2026-06-20-customer-management.md T13

Covers:
  - 3 个 ensure_*_table 跑两次幂等(不抛 1060/1061/1062)
"""
from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

from lumen_core.database import (
    ensure_customer_field_definitions_table,
    ensure_customer_follow_ups_table,
    ensure_customers_table,
)


def test_customers_table_ensure_idempotent():
    """``ensure_customers_table()`` 跑两次不抛错。"""
    ensure_customers_table()
    # 第二次必须不抛
    ensure_customers_table()


def test_all_three_customer_tables_ensure_idempotent():
    """3 张表 ensure_* 跑两次不抛错。"""
    ensure_customers_table()
    ensure_customer_follow_ups_table()
    ensure_customer_field_definitions_table()
    # 第二次全跑
    ensure_customers_table()
    ensure_customer_follow_ups_table()
    ensure_customer_field_definitions_table()