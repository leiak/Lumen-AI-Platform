"""RestrictedPython-based sandbox for M16 script skills."""
import ast
import builtins as _real_builtins
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from RestrictedPython import compile_restricted  # type: ignore[import-untyped]
from RestrictedPython.Guards import safe_globals as rp_safe_globals  # type: ignore[import-untyped]
from lumen_core.sandbox.restricted_globals import SAFE_GLOBALS, FORBIDDEN_NAMES
from lumen_core.skill_errors import SkillSecurityError, SkillTimeoutError, SkillExecutionError


def _ast_security_check(code: str) -> None:
    """Reject code that references forbidden names/attributes/imports."""
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise SkillSecurityError(f"forbidden name used: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            raise SkillSecurityError(f"forbidden attribute used: {node.attr}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_NAMES:
                    raise SkillSecurityError(
                        f"forbidden import: {alias.name}"
                    )
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in FORBIDDEN_NAMES:
                raise SkillSecurityError(
                    f"forbidden import from: {node.module}"
                )


class ScriptSandbox:
    @staticmethod
    def execute(code: str, input_data: dict, timeout: int) -> object:
        """Run user code with RestrictedPython + safe_globals + timeout.

        The user must define a `def main(input_data: dict)` function.
        Return value of main() is returned to the caller.
        """
        # 1. Static analysis
        _ast_security_check(code)

        # 2. Compile with RestrictedPython
        try:
            compiled = compile_restricted(code, filename="<m16-skill>")
        except SyntaxError as e:
            raise SkillExecutionError(f"Script syntax error: {e}")

        # 3. Build safe globals
        safe_globals = dict(SAFE_GLOBALS)
        # Use RestrictedPython's safe builtins (which include _getattr_ / _getitem_ guards
        # applied via their transform); layer in __import__ so that whitelisted
        # stdlib modules (e.g. `time`) can be imported. Forbidden names are caught
        # by the AST check above.
        rp_builtins = dict(rp_safe_globals["__builtins__"])
        rp_builtins["__import__"] = _real_builtins.__import__
        safe_globals["__builtins__"] = rp_builtins
        safe_globals["_input"] = input_data

        # 4. Execute with timeout
        def runner():
            exec(compiled, safe_globals)  # noqa: S102 — controlled sandbox
            if "main" not in safe_globals:
                raise SkillExecutionError("Script must define a `main(input_data)` function")
            return safe_globals["main"](**input_data)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(runner)
            try:
                return future.result(timeout=timeout)
            except FuturesTimeout:
                raise SkillTimeoutError(f"Script execution exceeded {timeout}s timeout")
