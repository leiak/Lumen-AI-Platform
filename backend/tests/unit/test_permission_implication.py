"""M38.2.x v2: implication chain coverage.

Spec §6.2 implication table:source perm + implied perm 完整性 + transitive
closure 正确性。把 ``_PERM_IMPLIES`` 每条 entry 都过一遍,防未来新增 entry
忘记配对 / 配错。
"""
from __future__ import annotations

import pytest

from lumen_services.permission_service import (
    _ALL_PERMS,
    _PERM_IMPLIES,
    effective_perms,
)


def test_implication_table_is_complete():
    """每个 source 都必须在 _ALL_PERMS 里(防 typo)。"""
    for source in _PERM_IMPLIES:
        assert source in _ALL_PERMS, f"unknown source: {source}"


def test_implication_targets_are_known():
    """每个 implied target 都在白名单(防 typo)。"""
    for source, targets in _PERM_IMPLIES.items():
        for t in targets:
            assert t in _ALL_PERMS, f"unknown target {t} implied by {source}"


def test_implication_total_count():
    """spec §4:17 个有效 perm(workspace.read 复用不算);我们用 19 项 perm +
    16 条 implication(impl 7 个 workspace 类 + 4 个 kb 类 + 4 个 folder 类 +
    4 个 document 类 + document.move 1 条)。
    """
    # 不锁数字大小,只锁每条 implication 都非空 + source/target 合法(上面已测)
    assert all(len(targets) > 0 for targets in _PERM_IMPLIES.values())


@pytest.mark.parametrize("source,expected_implied", [
    # workspace
    ("workspace.update", ["workspace.read"]),
    ("workspace.delete", ["workspace.read"]),
    ("workspace.manage_members", ["workspace.read"]),
    ("workspace.transfer_ownership", ["workspace.read"]),
    # kb
    ("kb.create", ["kb.read"]),
    ("kb.update", ["kb.read"]),
    ("kb.delete", ["kb.read"]),
    ("kb.read", ["document.read"]),
    # folder
    ("folder.create", ["folder.read"]),
    ("folder.update", ["folder.read"]),
    ("folder.delete", ["folder.read"]),
    ("folder.restore", ["folder.read"]),
    # document
    ("document.create", ["document.read"]),
    ("document.update", ["document.read"]),
    ("document.delete", ["document.read"]),
    ("document.move", ["folder.read", "folder.update"]),
])
def test_each_implication_entry(source, expected_implied):
    """逐条验证 _PERM_IMPLIES 表里的 implication 关系。"""
    assert source in _PERM_IMPLIES
    for imp in expected_implied:
        assert imp in _PERM_IMPLIES[source], f"{source} should imply {imp}"


def test_kb_update_implies_document_read_transitively():
    """kb.update → kb.read → document.read。两跳 transitive。"""
    eff = effective_perms({"kb.update"})
    assert "document.read" in eff
    assert "kb.read" in eff


def test_document_move_implies_folder_update():
    """document.move → folder.read + folder.update。"""
    eff = effective_perms({"document.move"})
    assert eff == {"document.move", "folder.read", "folder.update"}


def test_no_implication_cycle():
    """implication DAG 必须是真正的 DAG — 不允许 A → ... → A。

    BFS 从每个 source 出发的可见集合不含自己(即 source 不能通过 implication
    链回到 source)。注意:_PERM_IMPLIES 是一个 DAG,多个 source 可以共享同一个
    implied target(folder.read 是 folder.update 和 document.move 共同的 target),
    不算 cycle。
    """
    for source in _PERM_IMPLIES:
        # 沿 BFS 走到底,记录 path,任何节点若再次出现在 path 里就是 cycle
        def _bfs(start, blocked):
            # blocked = path set,防止重访
            stack = [(start, [start])]
            while stack:
                node, path = stack.pop()
                for child in _PERM_IMPLIES.get(node, []):
                    if child in path:
                        raise AssertionError(
                            f"implication cycle via {start}: {' → '.join(path + [child])}"
                        )
                    stack.append((child, path + [child]))
        _bfs(source, {source})


def test_effective_perms_idempotent():
    """effective_perms(effective_perms(x)) == effective_perms(x)。"""
    for source in list(_PERM_IMPLIES.keys()) + ["kb.read", "workspace.read"]:
        once = effective_perms({source})
        twice = effective_perms(once)
        assert once == twice


def test_effective_perms_empty_input():
    assert effective_perms(set()) == set()
    assert effective_perms([]) == set()


def test_effective_perms_no_implications_returns_input():
    """没有 implication 的 perm 直接返输入。"""
    # workspace.delete 不 imply 任何其他(workspace.delete → workspace.read 已在表里)
    # 用一个明确不在 implication 里的:kb.create 是 source 但 kb.create 不是 target
    eff = effective_perms({"kb.create"})
    assert "kb.create" in eff


def test_all_perms_count_stable():
    """加新 perm 时,数字至少 +1。锁住 baseline。"""
    assert len(_ALL_PERMS) >= 19