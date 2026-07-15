"""Tests for ScriptSandbox (M16 script skill type)."""
import pytest


def test_happy_path_returns_main_output():
    from lumen_core.sandbox.script_sandbox import ScriptSandbox
    code = "def main(x): return x * 2"
    result = ScriptSandbox.execute(code, {"x": 5}, timeout=5)
    assert result == 10


def test_rejects_import_os():
    from lumen_core.sandbox.script_sandbox import ScriptSandbox
    from lumen_core.skill_errors import SkillSecurityError
    with pytest.raises(SkillSecurityError, match="forbidden"):
        ScriptSandbox.execute("import os", {}, timeout=5)


def test_rejects_subprocess():
    from lumen_core.sandbox.script_sandbox import ScriptSandbox
    from lumen_core.skill_errors import SkillSecurityError
    with pytest.raises(SkillSecurityError, match="forbidden"):
        ScriptSandbox.execute(
            "import subprocess\nsubprocess.run(['ls'])", {}, timeout=5
        )


def test_rejects_open_call():
    from lumen_core.sandbox.script_sandbox import ScriptSandbox
    from lumen_core.skill_errors import SkillSecurityError
    with pytest.raises(SkillSecurityError, match="forbidden"):
        ScriptSandbox.execute("open('/etc/passwd')", {}, timeout=5)


def test_rejects_eval():
    from lumen_core.sandbox.script_sandbox import ScriptSandbox
    from lumen_core.skill_errors import SkillSecurityError
    with pytest.raises(SkillSecurityError, match="forbidden"):
        ScriptSandbox.execute("eval('1+1')", {}, timeout=5)


def test_timeout_raises_skill_timeout():
    from lumen_core.sandbox.script_sandbox import ScriptSandbox
    from lumen_core.skill_errors import SkillTimeoutError
    code = "import time\ntime.sleep(10)"
    with pytest.raises(SkillTimeoutError):
        ScriptSandbox.execute(code, {}, timeout=1)
