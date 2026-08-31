"""Compare SQLAlchemy model columns vs MySQL information_schema columns.

For each lumen_models/*.py module:
  - Reflect __tablename__
  - Walk class body, extract Column(...) and mapped_column(...) declarations
  - Resolve implicit vs explicit column names
  - Compare to information_schema.COLUMNS

Reports:
  - model_declared_but_db_missing   (drift: ORM will fail to insert/update)
  - db_extra                         (DB-only, not in model; usually safe, sometimes)
  - per-table column counts

Usage: cd backend && python scripts/audit_model_schema_drift.py
"""
import os
import re
import sys
import ast
from collections import defaultdict
from urllib.parse import urlparse

import pymysql


MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lumen_models")


def parse_db_url(url: str) -> dict:
    url = url.replace("mysql+pymysql://", "mysql://")
    p = urlparse(url)
    return {
        "host": p.hostname,
        "port": p.port,
        "user": p.username,
        "password": p.password,
        "database": p.path.lstrip("/"),
    }


def load_db_creds(env_path: str) -> dict:
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"DATABASE_URL\s*=\s*(\S+)", line.strip())
            if m:
                return parse_db_url(m.group(1))
    raise RuntimeError("DATABASE_URL not found in .env")


# ---------- AST walk: 找出每个 model class 的 __tablename__ + 所有 column 名 ----------
def extract_model_columns(path: str):
    """Return [(class_name, table_name, [col_names])] for each Model class.

    Also detect module-level ``Table("xxx", Base, Column(...), ...)`` calls
    so secondary association tables (e.g. role_permissions) are accounted for.
    """
    src = open(path, "r", encoding="utf-8").read()
    tree = ast.parse(src, filename=path)

    def _resolve_column(call_node, default_name):
        args = call_node.args
        if args:
            first = args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                return first.value
            return default_name
        for kw in call_node.keywords:
            if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                return kw.value.value
        return default_name

    def _is_column_call(value_node):
        if not isinstance(value_node, ast.Call):
            return False
        fn = value_node.func
        if isinstance(fn, ast.Name) and fn.id in ("Column", "mapped_column"):
            return True
        if isinstance(fn, ast.Attribute) and fn.attr in ("Column", "mapped_column"):
            return True
        return False

    result = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            tbl = None
            cols = []
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    tgt = stmt.targets[0]
                    if isinstance(tgt, ast.Name) and tgt.id == "__tablename__":
                        if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                            tbl = stmt.value.value
                        continue
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    tgt = stmt.targets[0]
                    if isinstance(tgt, ast.Name) and _is_column_call(stmt.value):
                        cols.append(_resolve_column(stmt.value, tgt.id))
                    continue
                if isinstance(stmt, ast.AnnAssign):
                    tgt = stmt.target
                    if isinstance(tgt, ast.Name) and _is_column_call(stmt.value):
                        cols.append(_resolve_column(stmt.value, tgt.id))
            if tbl or cols:
                result.append((node.name, tbl, cols))

        # 模式 3:模块级 Table("xxx", Base, Column(...), ...) association table
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name) and isinstance(node.value, ast.Call):
                fn = node.value.func
                if isinstance(fn, ast.Name) and fn.id == "Table" and node.value.args:
                    first = node.value.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        tbl_name = first.value
                        # Table 后续 args 是 metadata + 列定义;这里没展开
                        result.append((f"<Table:{tgt.id}>", tbl_name, set()))
    return result


# ---------- 主流程 ----------
def main():
    creds = load_db_creds(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
    conn = pymysql.connect(
        host=creds["host"], port=creds["port"], user=creds["user"],
        password=creds["password"], database=creds["database"], connect_timeout=10,
    )

    # 1. 收集模型声明: {table_name: {col_name, ...}}
    model_cols = defaultdict(set)
    model_files = {}

    def scan_dir(scan_root):
        for root, _, files in os.walk(scan_root):
            for fname in files:
                if not fname.endswith(".py") or fname == "__init__.py" or fname == "base.py":
                    continue
                path = os.path.join(root, fname)
                rel = os.path.relpath(path, os.path.dirname(MODEL_DIR))
                for cls_name, tbl, cols in extract_model_columns(path):
                    if not tbl:
                        continue
                    model_cols[tbl].update(cols)
                    model_files.setdefault(tbl, rel)

    scan_dir(MODEL_DIR)
    scan_dir(os.path.join(os.path.dirname(MODEL_DIR), "lumen_services"))

    # 2. 收集 DB 实际列: {table_name: {col_name, ...}}
    db_cols = defaultdict(set)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s",
            (creds["database"],),
        )
        for tbl, col in cur.fetchall():
            db_cols[tbl].add(col)
    conn.close()

    # 3. 对账
    drift_model_only = []  # 模型有,DB 没
    drift_db_only = []  # DB 有,模型没
    matched = 0
    for tbl in sorted(set(model_cols) | set(db_cols)):
        mset = model_cols.get(tbl, set())
        dset = db_cols.get(tbl, set())
        # 跳过只占位(Table 类型的二级表,没列详情)
        if tbl in model_files and not mset and model_files[tbl].endswith(".py"):
            # 是 Table(...) 二级表,无列详情,跳过列级对账
            continue
        for c in sorted(mset - dset):
            drift_model_only.append((tbl, c, model_files.get(tbl, "?")))
        for c in sorted(dset - mset):
            drift_db_only.append((tbl, c))
        matched += len(mset & dset)

    # 4. 输出
    print(f"模型声明的表: {len(model_cols)}")
    print(f"DB 实际表:   {len(db_cols)}")
    print(f"列对账匹配:  {matched}")
    print()

    print(f"=== 模型声明但 DB 缺失({len(drift_model_only)} 个列)— ORM 写入会报 Unknown column ===")
    if not drift_model_only:
        print("  (无 — 模型与 DB schema 100% 对齐)")
    for tbl, col, fn in drift_model_only:
        print(f"  {tbl:35s}.{col:30s}  ← {fn}")
    print()

    # DB-only 太多通常是 base 列(id/created_at/updated_at),过滤掉
    base_cols = {"id", "created_at", "updated_at", "deleted_at", "created_by_id"}
    db_only_filtered = [(t, c) for (t, c) in drift_db_only if c not in base_cols]
    print(f"=== DB 有但模型未声明(过滤 base 列后 {len(db_only_filtered)} 个)===")
    for tbl, col in db_only_filtered:
        print(f"  {tbl:35s}.{col}")
    if len(drift_db_only) > len(db_only_filtered):
        print(f"  ...另有 {len(drift_db_only) - len(db_only_filtered)} 个 base 列(id/created_at/updated_at 等)未列出")

    print()
    print(f"=== 完全没模型对应的 DB 表(可能没用 ORM 管,或模型被删了)===")
    no_model = sorted(set(db_cols) - set(model_cols))
    if no_model:
        print(f"  共 {len(no_model)} 张: {', '.join(no_model)}")
    else:
        print("  无")


if __name__ == "__main__":
    main()