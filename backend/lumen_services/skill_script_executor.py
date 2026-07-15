"""
SkillScriptExecutor — 执行 skill content 里内嵌的 Python 脚本。

设计原则：
- 脚本写入临时 .py 文件后通过 subprocess 执行（避免 eval 安全问题）
- 后台线程执行，支持 timeout
- stdout/stderr 捕获，returncode 报告
- 超时 → SIGKILL → 返回 timeout 错误
- 脚本参数通过环境变量 JSON 传入（避免 shell injection）
"""

import json
import os
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


class SkillScriptResult:
    """执行结果容器。"""

    def __init__(
        self,
        success: bool,
        stdout: str = "",
        stderr: str = "",
        returncode: int = -1,
        error: Optional[str] = None,
        latency_ms: int = 0,
    ):
        self.success = success
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.error = error
        self.latency_ms = latency_ms

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "error": self.error,
            "latency_ms": self.latency_ms,
        }


class SkillScriptExecutor:
    """执行 skill script 类型技能的 Python 脚本。"""

    # 全局默认超时（秒）
    DEFAULT_TIMEOUT = 30

    def execute(
        self,
        script_content: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> SkillScriptResult:
        """
        执行 Python 脚本。

        Args:
            script_content: Python 脚本源码（字符串）
            params: 参数字典，会通过环境变量 SKILL_PARAMS 传入（JSON 编码）
            timeout: 超时秒数，默认 30

        Returns:
            SkillScriptResult
        """
        params = params or {}
        start = time.monotonic()

        # 生成唯一临时文件，保证并发安全
        script_id = uuid.uuid4().hex[:8]
        tmp_dir = Path(tempfile.gettempdir()) / "lumen_skill_scripts"
        tmp_dir.mkdir(exist_ok=True)
        script_path = tmp_dir / f"skill_{script_id}.py"

        try:
            script_path.write_text(script_content, encoding="utf-8")

            env = os.environ.copy()
            env["SKILL_PARAMS"] = json.dumps(params, ensure_ascii=False)

            proc = subprocess.Popen(
                ["python", str(script_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
            )

            def _wait():
                proc.wait()

            t = threading.Thread(target=_wait, daemon=True)
            t.start()
            t.join(timeout=timeout)

            latency_ms = int((time.monotonic() - start) * 1000)

            if proc.returncode is None:
                # 超时，进程还在跑 → SIGKILL
                try:
                    proc.kill()
                except OSError:
                    pass
                return SkillScriptResult(
                    success=False,
                    error=f"Script execution timed out after {timeout}s",
                    latency_ms=latency_ms,
                )

            stdout, stderr = proc.communicate()
            success = proc.returncode == 0

            return SkillScriptResult(
                success=success,
                stdout=stdout,
                stderr=stderr,
                returncode=proc.returncode,
                latency_ms=latency_ms,
                error=None if success else f"Exit code {proc.returncode}",
            )

        except Exception as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            return SkillScriptResult(
                success=False,
                error=f"{type(e).__name__}: {e}",
                latency_ms=latency_ms,
            )

        finally:
            # 清理临时文件
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                pass
