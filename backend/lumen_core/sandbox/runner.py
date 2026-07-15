"""RestrictedPython 沙箱:编译并执行用户 Python 源码。

约束(由 RestrictedPython 8.x + 白名单强制):
- 禁止 import(compile_restricted 拒绝大多数隐式 import,运行时 __import__ 缺席 → ImportError → NameError)
- 禁止 open / file I/O(safe_globals.__builtins__ 中没有 open → NameError)
- 禁止网络(没有 socket 模块)
- 允许白名单:json, re, math, 基础类型(str/int/list/dict/...)
- 用户用 RESULT = <expr> 提交结果(默认变量名 RESULT,可配)

API drift 备注(8.x vs 计划写的 6.x):
- `safe_globals`(dict)是 8.x 顶层暴露的预制 globals,内含 `__builtins__` + `_getattr_=safer_getattr`。
  计划中提到的 `safe_builtins` 在 8.x 中也存在,但只是 builtins dict(不包 __builtins__ 包装),
  用 safe_globals 更省事。
- `Guards.guarded_iter` 在 8.x 中已删除;新名字是 `guarded_iter_unpack_sequence`/`guarded_unpack_sequence`。
  计划中的 `safe_getattr` → 8.x 是 `safer_getattr`(`safe_getattr` 已被移除/重命名)。
- `PrintCollector` 仍是一个 class,签名是 `__init__(self, _getattr_=None)`。
  8.x 的 transform 会在用户模块顶端注入 `_print = _print_(_getattr_)`,
  其中 `_print_` 是 callable,接收 `_getattr_` 并返回 PrintCollector 实例。
  要把 print() 转发到外部 StringIO,需子类化 PrintCollector 并在 `write` 中转发。
"""
import io
import json
import math
import re
from typing import Any, Mapping

from RestrictedPython import compile_restricted, safe_globals  # type: ignore[import-untyped]
from RestrictedPython.Guards import (  # type: ignore[import-untyped]
    full_write_guard,
    guarded_iter_unpack_sequence,
    safer_getattr,
)
from RestrictedPython.PrintCollector import PrintCollector  # type: ignore[import-untyped]


class _StdoutCollector(PrintCollector):
    """PrintCollector 子类,除收集到 self.txt 外,还把每次 write 转发到外部 StringIO。

    RestrictedPython 8.x 的 transform 把 `print(x)` 编译成 `_print._call_print(x)`,
    而 `_call_print` 最终调用内置 `print(x, file=_print)`,内置 print 会调
    `_print.write(text)`。所以我们只需覆写 `write` 即可。
    """

    def __init__(self, stdout: io.StringIO, _getattr_: Any = None) -> None:
        super().__init__(_getattr_=_getattr_)
        self._stdout = stdout

    def write(self, text: str) -> None:
        # 父类把 text 收集到 self.txt(可由 `_print()` 取回);这里再额外转发到外部 buffer。
        super().write(text)
        self._stdout.write(text)


def _make_print_factory(stdout: io.StringIO):
    """构造一个 `_print_` 工厂,绑定到指定 stdout。"""

    def _factory(_getattr_: Any = None) -> _StdoutCollector:
        return _StdoutCollector(stdout, _getattr_=_getattr_)

    return _factory


async def run_python_restricted(
    code: str,
    inputs: Mapping[str, Any],
    output_var: str,
    stdout: io.StringIO,
) -> Any:
    """Compile + exec 用户代码,返回 `output_var` 的值(若未设置则返回 None)。

    Args:
        code: 用户 Python 源码(必须用 `RESULT = <expr>` 提交结果,除非传入其他 output_var)。
        inputs: 注入为 globals 的额外变量映射(例如上游节点的输出)。
        output_var: 用户代码用来提交结果的变量名。
        stdout: 接收 `print()` 输出的 StringIO buffer。

    Returns:
        `output_var` 在执行后的值;若用户未设置则返回 None。

    Raises:
        ValueError: 编译失败(包 SyntaxError)。
        NameError: 尝试 import / 调用未在白名单中的名字(open 等)。
    """
    # 1. Compile
    try:
        compiled = compile_restricted(code, filename="<code_node>", mode="exec")
    except SyntaxError as e:
        raise ValueError(f"compile error: {e}") from e

    # 2. Build globals
    # safe_globals 已经把 __builtins__ 包成 safe builtins,且内置 _getattr_=safer_getattr。
    # 我们再补上 _print_/_getiter_/_write_ 守卫,以及白名单模块。
    glb: dict[str, Any] = safe_globals.copy()
    glb["__name__"] = "__code_node__"
    # 8.x transformer 在类定义处改写为 `class X(metaclass=__metaclass__)`,所以要塞一个 type。
    glb["__metaclass__"] = type
    glb["_getattr_"] = safer_getattr
    glb["_getiter_"] = guarded_iter_unpack_sequence
    glb["_write_"] = full_write_guard
    glb["json"] = json
    glb["re"] = re
    glb["math"] = math
    glb["_print_"] = _make_print_factory(stdout)

    # Inject user inputs as globals(覆盖白名单:如果用户 inputs 里有同名 key,以 inputs 为准)
    glb.update(inputs)

    # 3. Execute
    # 把 ImportError 重新包装为 NameError,与公开契约"未授权的名字一律 NameError"对齐。
    try:
        exec(compiled, glb)  # noqa: S102 — 这是受限 exec(compile_restricted 已审过 AST)
    except ImportError as e:
        raise NameError(str(e)) from e

    # 4. Return result
    return glb.get(output_var)
